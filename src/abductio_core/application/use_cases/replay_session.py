from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from abductio_core.application.result import SessionResult, StopReason
from abductio_core.domain.invariants import H_OTHER_ID, enforce_absorber


def replay_session(audit_trace: Iterable[Dict[str, object]]) -> SessionResult:
    ledger: Dict[str, float] = {}
    roots: Dict[str, Dict[str, object]] = {}
    required_root_ids: List[str] = []
    operation_log: List[Dict[str, object]] = []
    stop_reason: Optional[StopReason] = None

    for event in audit_trace:
        et = event.get("event_type")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if et == "SESSION_INITIALIZED":
            required_root_ids = list(payload.get("roots", [])) if isinstance(payload.get("roots"), list) else []
            ledger = dict(payload.get("ledger", {})) if isinstance(payload.get("ledger"), dict) else {}
            for rid in required_root_ids:
                roots.setdefault(str(rid), {"id": str(rid)})
        elif et == "OP_EXECUTED":
            operation_log.append(
                {
                    "op_type": payload.get("op_type"),
                    "target_id": payload.get("target_id"),
                    "credits_before": payload.get("credits_before"),
                    "credits_after": payload.get("credits_after"),
                }
            )
        elif et == "ROOT_SCOPED":
            rid = payload.get("root_id")
            if isinstance(rid, str):
                roots.setdefault(rid, {"id": rid})
                roots[rid]["status"] = "SCOPED"
                roots[rid].setdefault("obligations", {})
        elif et == "SLOT_DECOMPOSED":
            slot_node_key = payload.get("slot_node_key")
            if isinstance(slot_node_key, str) and ":" in slot_node_key:
                rid, slot_key = slot_node_key.split(":", 1)
                roots.setdefault(rid, {"id": rid, "status": "SCOPED", "obligations": {}})
                obligations = roots[rid].setdefault("obligations", {})
                if isinstance(obligations, dict):
                    obligations.setdefault(slot_key, {})
                    if isinstance(obligations[slot_key], dict):
                        obligations[slot_key]["children"] = list(payload.get("children", []))
                        obligations[slot_key]["decomp_type"] = payload.get("type")
                        obligations[slot_key]["coupling"] = payload.get("coupling")
        elif et == "NODE_EVALUATED":
            nk = payload.get("node_key")
            if isinstance(nk, str):
                if ":" in nk:
                    rid = nk.split(":", 1)[0]
                    roots.setdefault(rid, {"id": rid, "status": "SCOPED", "obligations": {}})
        elif et == "DAMPING_APPLIED":
            rid = payload.get("root_id")
            p_new = payload.get("p_new")
            if isinstance(rid, str) and isinstance(p_new, (int, float)):
                ledger[rid] = float(p_new)
                named = [r for r in required_root_ids if r != H_OTHER_ID]
                if named:
                    enforce_absorber(ledger, named)
        elif et == "STOP_REASON_RECORDED":
            reason = payload.get("stop_reason")
            if isinstance(reason, str):
                try:
                    stop_reason = StopReason(reason)
                except ValueError:
                    stop_reason = None

    named = [r for r in required_root_ids if r != H_OTHER_ID]
    if named:
        enforce_absorber(ledger, named)

    return SessionResult(
        roots={k: dict(v) for k, v in roots.items()},
        ledger=dict(ledger),
        audit=list(audit_trace),
        stop_reason=stop_reason,
        credits_remaining=0,
        total_credits_spent=len(operation_log),
        operation_log=operation_log,
    )
