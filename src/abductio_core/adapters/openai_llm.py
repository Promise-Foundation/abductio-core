from __future__ import annotations

import importlib
import json
import os
import time
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def _first_text(response: Any) -> str:
    if hasattr(response, "output_text") and response.output_text:
        return str(response.output_text)
    try:
        output = response.output  # type: ignore[attr-defined]
        if output and hasattr(output[0], "content") and output[0].content:
            return str(output[0].content[0].text)  # type: ignore[index]
    except Exception:
        pass
    return ""


def _chat_text(response: Any) -> str:
    try:
        choices = response.choices  # type: ignore[attr-defined]
        if choices:
            message = choices[0].message
            if message and hasattr(message, "content"):
                return str(message.content)
    except Exception:
        pass
    return ""


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class OpenAIJsonClient:
    api_key: Optional[str] = None
    model: str = "gpt-4.1-mini"
    temperature: float = 0.0
    timeout_s: float = 60.0
    max_retries: int = 3
    retry_backoff_s: float = 0.8

    def __post_init__(self) -> None:
        key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required")
        try:
            openai_mod = importlib.import_module("openai")
        except Exception as exc:
            raise RuntimeError("openai package is required") from exc
        openai_cls = getattr(openai_mod, "OpenAI", None)
        if openai_cls is None:
            raise RuntimeError("openai package is required")
        self._client = openai_cls(api_key=key, timeout=self.timeout_s)

    def complete_json(self, *, system: str, user: str) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            text = ""
            try:
                response = self._client.responses.create(
                    model=self.model,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                    input=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                text = _first_text(response).strip()
            except Exception as exc:
                last_exc = exc

            if not text:
                try:
                    response = self._client.chat.completions.create(
                        model=self.model,
                        temperature=self.temperature,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    )
                    text = _chat_text(response).strip()
                except Exception as exc:
                    last_exc = exc
                    text = ""

            if not text:
                time.sleep(self.retry_backoff_s * (attempt + 1))
                continue

            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    payload.setdefault(
                        "_provenance",
                        {
                            "provider": "openai",
                            "model": self.model,
                            "temperature": self.temperature,
                            "timeout_s": self.timeout_s,
                            "response_format": "json_object",
                            "system_hash": _hash_text(system),
                            "user_hash": _hash_text(user),
                            "response_hash": _hash_text(text),
                        },
                    )
                return payload
            except json.JSONDecodeError as exc:
                last_exc = exc
                time.sleep(self.retry_backoff_s * (attempt + 1))
                continue

        raise RuntimeError(f"LLM did not return valid JSON after retries: {last_exc}") from last_exc


def _validate_evaluation(outcome: Dict[str, Any]) -> None:
    missing = [
        key
        for key in (
            "p",
            "A",
            "B",
            "C",
            "D",
            "evidence_ids",
            "reasoning_summary",
            "defeaters",
            "uncertainty_source",
            "evidence_quality",
            "assumptions",
        )
        if key not in outcome
    ]
    if missing:
        raise RuntimeError(f"LLM evaluation missing keys: {missing}")
    try:
        p_value = float(outcome["p"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("LLM evaluation p is not a number") from exc
    if not 0.0 <= p_value <= 1.0:
        raise RuntimeError("LLM evaluation p out of range")
    for key in ("A", "B", "C", "D"):
        value = outcome[key]
        if isinstance(value, bool):
            raise RuntimeError(f"LLM evaluation {key} must be int 0..2")
        try:
            score = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"LLM evaluation {key} is not an int") from exc
        if score < 0 or score > 2:
            raise RuntimeError(f"LLM evaluation {key} out of range")
    evidence_ids = outcome.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not all(isinstance(item, str) and item for item in evidence_ids):
        raise RuntimeError("LLM evaluation evidence_ids must be a non-empty list of strings (or [] when none)")
    evidence_quality = outcome.get("evidence_quality")
    if evidence_quality not in {"direct", "indirect", "weak", "none"}:
        raise RuntimeError("LLM evaluation evidence_quality must be one of {direct,indirect,weak,none}")
    if not isinstance(outcome.get("reasoning_summary"), str) or not outcome["reasoning_summary"].strip():
        raise RuntimeError("LLM evaluation reasoning_summary must be a non-empty string")
    defeaters = outcome.get("defeaters")
    if not isinstance(defeaters, list) or not all(isinstance(item, str) for item in defeaters):
        raise RuntimeError("LLM evaluation defeaters must be a list of strings")
    if not isinstance(outcome.get("uncertainty_source"), str) or not outcome["uncertainty_source"].strip():
        raise RuntimeError("LLM evaluation uncertainty_source must be a non-empty string")
    assumptions = outcome.get("assumptions")
    if not isinstance(assumptions, list) or not all(isinstance(item, str) for item in assumptions):
        raise RuntimeError("LLM evaluation assumptions must be a list of strings")
    quotes = outcome.get("quotes")
    if quotes is not None:
        if not isinstance(quotes, list):
            raise RuntimeError("LLM evaluation quotes must be a list")
        for quote in quotes:
            if not isinstance(quote, dict):
                raise RuntimeError("LLM evaluation quote must be object")
            if not quote.get("evidence_id") or not quote.get("exact_quote"):
                raise RuntimeError("LLM evaluation quote requires evidence_id and exact_quote")


def _validate_slot_decomposition(out: Dict[str, Any]) -> None:
    if not out.get("ok", True):
        return
    if "children" not in out:
        raise RuntimeError("LLM slot decomposition missing children")
    if out.get("type") not in {"AND", "OR"}:
        raise RuntimeError("LLM slot decomposition type must be AND or OR")
    children = out.get("children")
    if not isinstance(children, list) or len(children) < 2:
        raise RuntimeError("LLM slot decomposition children must be list with >=2 items")
    if out.get("type") == "AND":
        c = out.get("coupling")
        try:
            cf = float(c)
        except Exception as exc:
            raise RuntimeError("LLM slot decomposition coupling must be float") from exc
        if cf not in {0.20, 0.50, 0.80, 0.95}:
            raise RuntimeError("LLM slot decomposition coupling must be one of {0.20,0.50,0.80,0.95}")
    for child in children:
        if not isinstance(child, dict):
            raise RuntimeError("LLM slot decomposition child must be object")
        if not (child.get("child_id") or child.get("id")):
            raise RuntimeError("LLM slot decomposition child missing child_id/id")
        if not child.get("statement"):
            raise RuntimeError("LLM slot decomposition child missing statement")
        if "falsifiable" not in child or not isinstance(child.get("falsifiable"), bool):
            raise RuntimeError("LLM slot decomposition child missing falsifiable boolean")
        if not isinstance(child.get("test_procedure"), str) or not child.get("test_procedure"):
            raise RuntimeError("LLM slot decomposition child missing test_procedure")
        overlap = child.get("overlap_with_siblings")
        if overlap is None or not isinstance(overlap, list):
            raise RuntimeError("LLM slot decomposition child missing overlap_with_siblings list")
        role = child.get("role", "NEC")
        if role not in {"NEC", "EVID"}:
            raise RuntimeError("LLM slot decomposition child role must be NEC or EVID")


@dataclass
class OpenAIDecomposerPort:
    client: OpenAIJsonClient
    required_slots_hint: List[str]
    scope: Optional[str] = None
    root_statements: Optional[Dict[str, str]] = None
    default_coupling: float = 0.80

    def decompose(self, target_id: str) -> Dict[str, Any]:
        root_id, slot_key, child_id = _parse_node_key(target_id)
        root_statement = ""
        if root_id and self.root_statements:
            root_statement = self.root_statements.get(root_id, "")
        if ":" in target_id:
            system = (
                "You are the ABDUCTIO MVP decomposer.\n"
                "Return ONLY JSON.\n"
                "Task: decompose a SLOT into 2-5 children.\n"
                "Output schema:\n"
                "{\n"
                "  \"ok\": true,\n"
                "  \"type\": \"AND\"|\"OR\",\n"
                "  \"coupling\": 0.20|0.50|0.80|0.95 (required if type==AND),\n"
                "  \"children\": [\n"
                "    {\n"
                "      \"child_id\":\"c1\",\n"
                "      \"statement\":\"...\",\n"
                "      \"role\":\"NEC\"|\"EVID\",\n"
                "      \"falsifiable\": true,\n"
                "      \"test_procedure\": \"what evidence would raise or lower p\",\n"
                "      \"overlap_with_siblings\": []\n"
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}\n"
                "Constraints:\n"
                "- Each child must be falsifiable and tied to a test procedure.\n"
                "- Siblings should be non-overlapping unless overlap is explicitly listed.\n"
                "- Use type AND unless explicitly instructed otherwise.\n"
                "- Prefer NEC children.\n"
                "- Keep statements concrete and necessary-condition-like.\n"
            )
            user = json.dumps(
                {
                    "task": "decompose_slot",
                    "target_id": target_id,
                    "root_id": root_id,
                    "root_statement": root_statement,
                    "slot_key": slot_key,
                    "scope": self.scope or "",
                    "preferred_type": "AND",
                }
            )
            out = self.client.complete_json(system=system, user=user)

            if not isinstance(out, dict):
                out = {}
            out.setdefault("ok", True)
            out.setdefault("type", "AND")
            if out["type"] == "AND":
                out.setdefault("coupling", self.default_coupling)
            out.setdefault(
                "children",
                [
                    {
                        "child_id": "c1",
                        "statement": f"{target_id} part 1 holds",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": f"Observe evidence that {target_id} part 1 holds",
                        "overlap_with_siblings": [],
                    },
                    {
                        "child_id": "c2",
                        "statement": f"{target_id} part 2 holds",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": f"Observe evidence that {target_id} part 2 holds",
                        "overlap_with_siblings": [],
                    },
                ],
            )
            _validate_slot_decomposition(out)
            return out

        system = (
            "You are the ABDUCTIO MVP decomposer.\n"
            "Return ONLY JSON.\n"
            "Task: scope a ROOT into required template slot statements.\n"
            "Return {\"ok\": true, <slot>_statement: <string>, ...}.\n"
        )
        user = json.dumps(
            {
                "task": "scope_root",
                "target_id": target_id,
                "root_id": root_id,
                "root_statement": root_statement,
                "scope": self.scope or "",
                "required_slots": self.required_slots_hint,
            }
        )
        out = self.client.complete_json(system=system, user=user)
        if not isinstance(out, dict):
            out = {}
        out.setdefault("ok", True)
        for slot in self.required_slots_hint:
            out.setdefault(f"{slot}_statement", f"{target_id} satisfies {slot}")
        return out


@dataclass
class OpenAIEvaluatorPort:
    client: OpenAIJsonClient
    scope: Optional[str] = None
    root_statements: Optional[Dict[str, str]] = None
    evidence_items: Optional[List[Dict[str, Any]]] = None

    def evaluate(self, node_key: str) -> Dict[str, Any]:
        root_id, slot_key, child_id = _parse_node_key(node_key)
        root_statement = ""
        if root_id and self.root_statements:
            root_statement = self.root_statements.get(root_id, "")
        system = (
            "You are an evaluator for ABDUCTIO MVP.\n"
            "Return ONLY a single JSON object matching:\n"
            "{\n"
            "  \"p\": number in [0,1],\n"
            "  \"A\": int 0..2,\n"
            "  \"B\": int 0..2,\n"
            "  \"C\": int 0..2,\n"
            "  \"D\": int 0..2,\n"
            "  \"evidence_ids\": [\"EV-1\", \"EV-2\"],\n"
            "  \"quotes\": [{\"evidence_id\":\"EV-1\",\"exact_quote\":\"...\",\"location\":{}}],\n"
            "  \"evidence_quality\": \"direct\"|\"indirect\"|\"weak\"|\"none\",\n"
            "  \"reasoning_summary\": \"short justification referencing evidence ids\",\n"
            "  \"defeaters\": [\"what would change my mind\"],\n"
            "  \"uncertainty_source\": \"missing evidence / ambiguity\",\n"
            "  \"assumptions\": []\n"
            "}\n"
            "Rules:\n"
            "- Use ONLY facts present in the evidence packet; list any assumptions explicitly.\n"
            "- If no evidence supports the claim, set evidence_ids to [] and evidence_quality to \"none\".\n"
        )
        user = json.dumps(
            {
                "task": "evaluate",
                "node_key": node_key,
                "root_id": root_id,
                "root_statement": root_statement,
                "slot_key": slot_key,
                "child_id": child_id,
                "scope": self.scope or "",
                "evidence_items": self.evidence_items or [],
            }
        )
        out = self.client.complete_json(system=system, user=user)
        if not isinstance(out, dict):
            raise RuntimeError("LLM evaluation is not an object")
        _validate_evaluation(out)
        return out


def _parse_node_key(node_key: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    parts = node_key.split(":")
    if len(parts) == 1:
        return node_key, None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], parts[1], ":".join(parts[2:])
