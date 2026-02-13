from __future__ import annotations

import importlib
import json
import os
import time
import hashlib
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from abductio_core.application.dto import EvidenceItem


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


def _extract_json_object(text: str) -> Dict[str, Any]:
    candidate = str(text or "").strip()
    if not candidate:
        raise json.JSONDecodeError("empty response", candidate, 0)

    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    fenced = candidate
    if fenced.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", fenced, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```$", "", fenced)
        try:
            payload = json.loads(fenced)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        snippet = candidate[start : end + 1]
        payload = json.loads(snippet)
        if isinstance(payload, dict):
            return payload

    payload = json.loads(candidate)
    if isinstance(payload, dict):
        return payload
    raise json.JSONDecodeError("response JSON is not an object", candidate, 0)


def _exception_chain(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"
    parts: List[str] = []
    seen: set[int] = set()
    cursor: Exception | None = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        parts.append(f"{type(cursor).__name__}: {cursor}")
        nxt = getattr(cursor, "__cause__", None) or getattr(cursor, "__context__", None)
        cursor = nxt if isinstance(nxt, Exception) else None
    return " <- ".join(parts)


def _is_non_retryable_error(exc: Exception | None) -> bool:
    if exc is None:
        return False
    names = {type(exc).__name__}
    nested = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if isinstance(nested, Exception):
        names.add(type(nested).__name__)
    return bool(
        names
        & {
            "AuthenticationError",
            "PermissionDeniedError",
            "BadRequestError",
            "NotFoundError",
            "UnprocessableEntityError",
        }
    )


@dataclass
class OpenAIJsonClient:
    api_key: Optional[str] = None
    model: str = "gpt-4.1-mini"
    temperature: float = 0.0
    timeout_s: float = 60.0
    max_retries: int = 6
    retry_backoff_s: float = 1.0
    retry_backoff_max_s: float = 15.0
    retry_jitter_s: float = 0.25
    fallback_models: Tuple[str, ...] = ()
    base_url: Optional[str] = None

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
        base_url = self.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        kwargs: Dict[str, Any] = {"api_key": key, "timeout": self.timeout_s}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai_cls(**kwargs)

    def _sleep_for_retry(self, attempt: int) -> None:
        delay = float(self.retry_backoff_s) * (2**attempt)
        if self.retry_backoff_max_s > 0:
            delay = min(delay, float(self.retry_backoff_max_s))
        if self.retry_jitter_s > 0:
            delay += random.uniform(0.0, float(self.retry_jitter_s))
        if delay > 0:
            time.sleep(delay)

    def _model_candidates(self) -> List[str]:
        models: List[str] = []
        raw_fallbacks: List[str] = []
        if isinstance(self.fallback_models, str):
            raw_fallbacks = [part.strip() for part in self.fallback_models.split(",")]
        else:
            raw_fallbacks = [str(part).strip() for part in self.fallback_models]
        for candidate in [str(self.model).strip(), *raw_fallbacks]:
            if candidate and candidate not in models:
                models.append(candidate)
        return models or ["gpt-4.1-mini"]

    def _request_text(self, *, model: str, system: str, user: str) -> Tuple[str, Optional[Exception]]:
        last_exc: Optional[Exception] = None
        text = ""
        try:
            response = self._client.responses.create(
                model=model,
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

        if text:
            return text, last_exc

        try:
            response = self._client.chat.completions.create(
                model=model,
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
        return text, last_exc

    def complete_json(self, *, system: str, user: str) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        model_candidates = self._model_candidates()
        total_attempts = max(1, int(self.max_retries))
        for model_idx, model_name in enumerate(model_candidates):
            for attempt in range(total_attempts):
                text, request_exc = self._request_text(model=model_name, system=system, user=user)
                if text:
                    try:
                        payload = _extract_json_object(text)
                        payload.setdefault(
                            "_provenance",
                            {
                                "provider": "openai",
                                "model": model_name,
                                "temperature": self.temperature,
                                "timeout_s": self.timeout_s,
                                "response_format": "json_object",
                                "system_hash": _hash_text(system),
                                "user_hash": _hash_text(user),
                                "response_hash": _hash_text(text),
                                "attempt": attempt + 1,
                                "fallback_model_used": model_idx > 0,
                            },
                        )
                        return payload
                    except Exception as exc:
                        last_exc = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
                else:
                    last_exc = request_exc or RuntimeError("empty response text from OpenAI APIs")

                should_retry = attempt < (total_attempts - 1)
                if should_retry and not _is_non_retryable_error(last_exc):
                    self._sleep_for_retry(attempt)
                    continue
                break

            if model_idx < len(model_candidates) - 1:
                self._sleep_for_retry(0)

        detail = _exception_chain(last_exc)
        raise RuntimeError(
            f"LLM did not return valid JSON after retries across models {model_candidates}: {detail}"
        ) from last_exc


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
            "discriminator_ids",
            "discriminator_payloads",
            "entailment",
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
    discriminator_ids = outcome.get("discriminator_ids")
    if not isinstance(discriminator_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in discriminator_ids
    ):
        raise RuntimeError("LLM evaluation discriminator_ids must be a list of non-empty strings (or [])")
    discriminator_payloads = outcome.get("discriminator_payloads")
    if not isinstance(discriminator_payloads, list):
        raise RuntimeError("LLM evaluation discriminator_payloads must be a list")
    for payload in discriminator_payloads:
        if not isinstance(payload, dict):
            raise RuntimeError("LLM evaluation discriminator_payload must be an object")
        discriminator_id = payload.get("id")
        pair = payload.get("pair")
        direction = payload.get("direction")
        typed_evidence_ids = payload.get("evidence_ids")
        if not isinstance(discriminator_id, str) or not discriminator_id.strip():
            raise RuntimeError("LLM evaluation discriminator_payload.id must be a non-empty string")
        if not isinstance(pair, str) or not pair.strip():
            raise RuntimeError("LLM evaluation discriminator_payload.pair must be a non-empty string")
        if not isinstance(direction, str) or not direction.strip():
            raise RuntimeError("LLM evaluation discriminator_payload.direction must be a non-empty string")
        if not isinstance(typed_evidence_ids, list) or not all(
            isinstance(item, str) and item.strip() for item in typed_evidence_ids
        ):
            raise RuntimeError("LLM evaluation discriminator_payload.evidence_ids must be a list of non-empty strings")
        if discriminator_id not in discriminator_ids:
            raise RuntimeError("LLM evaluation discriminator_payload.id must appear in discriminator_ids")
    entailment = str(outcome.get("entailment", "")).strip().upper()
    if entailment not in {"SUPPORTS", "CONTRADICTS", "NEUTRAL", "UNKNOWN"}:
        raise RuntimeError("LLM evaluation entailment must be one of {SUPPORTS,CONTRADICTS,NEUTRAL,UNKNOWN}")
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

    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        root_id, slot_key, child_id = _parse_node_key(node_key)
        root_statement = ""
        if root_id and self.root_statements:
            root_statement = self.root_statements.get(root_id, "")
        context = context or {}
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
            "  \"discriminator_ids\": [\"disc:H1|H2\"],\n"
            "  \"discriminator_payloads\": [\n"
            "    {\n"
            "      \"id\": \"disc:H1|H2\",\n"
            "      \"pair\": \"H1|H2\",\n"
            "      \"direction\": \"FAVORS_LEFT\"|\"FAVORS_RIGHT\"|\"SUPPORTS\"|\"CONTRADICTS\"|\"NEUTRAL\",\n"
            "      \"evidence_ids\": [\"EV-1\"]\n"
            "    }\n"
            "  ],\n"
            "  \"entailment\": \"SUPPORTS\"|\"CONTRADICTS\"|\"NEUTRAL\"|\"UNKNOWN\",\n"
            "  \"non_discriminative\": boolean,\n"
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
            "- Use contrastive.candidate_discriminator_ids only; if none apply, return discriminator_ids=[] and discriminator_payloads=[].\n"
            "- If discriminator_ids is non-empty, include matching discriminator_payloads and cite supporting evidence_ids.\n"
            "- Use entailment=NEUTRAL when evidence does not discriminate among active alternatives.\n"
        )
        if evidence_items is not None:
            resolved_items: List[Dict[str, Any]] = []
            for item in evidence_items:
                if isinstance(item, EvidenceItem):
                    resolved_items.append(
                        {
                            "id": item.id,
                            "source": item.source,
                            "text": item.text,
                            "location": item.location,
                            "metadata": dict(item.metadata),
                        }
                    )
                elif isinstance(item, dict):
                    resolved_items.append(item)
            evidence_payload = resolved_items
        else:
            evidence_payload = self.evidence_items or []

        user = json.dumps(
            {
                "task": "evaluate",
                "node_key": node_key,
                "node_statement": statement,
                "root_id": root_id,
                "root_statement": root_statement,
                "parent_statement": context.get("parent_statement", ""),
                "role": context.get("role", ""),
                "slot_key": slot_key,
                "child_id": child_id,
                "scope": self.scope or "",
                "contrastive": context.get("contrastive", {}),
                "evidence_items": evidence_payload,
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
