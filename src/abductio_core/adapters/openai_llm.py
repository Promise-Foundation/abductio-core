from __future__ import annotations

import importlib
import json
import os
import time
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
                return json.loads(text)
            except json.JSONDecodeError as exc:
                last_exc = exc
                time.sleep(self.retry_backoff_s * (attempt + 1))
                continue

        raise RuntimeError(f"LLM did not return valid JSON after retries: {last_exc}") from last_exc


def _validate_evaluation(outcome: Dict[str, Any]) -> None:
    missing = [key for key in ("p", "A", "B", "C", "D", "evidence_refs") if key not in outcome]
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
    refs = str(outcome.get("evidence_refs", "")).strip()
    if not refs or refs == "(empty)":
        raise RuntimeError("LLM evaluation evidence_refs must be non-empty")


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
                "    {\"child_id\":\"c1\",\"statement\":\"...\",\"role\":\"NEC\"|\"EVID\"},\n"
                "    ...\n"
                "  ]\n"
                "}\n"
                "Constraints:\n"
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
                    {"child_id": "c1", "statement": f"{target_id} part 1 holds", "role": "NEC"},
                    {"child_id": "c2", "statement": f"{target_id} part 2 holds", "role": "NEC"},
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
            "  \"evidence_refs\": \"ref1\" (non-empty)\n"
            "}\n"
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
