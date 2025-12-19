from __future__ import annotations

from typing import Dict

from abductio_core.application.dto import SessionRequest
from abductio_core.application.result import SessionResult, StopReason
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.canonical import canonical_id_for_statement
from abductio_core.domain.invariants import H_OTHER_ID, enforce_absorber
from abductio_core.domain.model import HypothesisSet, Node, RootHypothesis


def _init_hypothesis_set(request: SessionRequest) -> HypothesisSet:
    roots: Dict[str, RootHypothesis] = {}
    ledger: Dict[str, float] = {}
    named_roots = request.roots
    count_named = len(named_roots)
    gamma = request.config.gamma
    base_p = (1.0 - gamma) / count_named if count_named else 0.0

    for root in named_roots:
        canonical_id = canonical_id_for_statement(root.statement)
        roots[root.root_id] = RootHypothesis(
            root_id=root.root_id,
            statement=root.statement,
            exclusion_clause=root.exclusion_clause,
            canonical_id=canonical_id,
        )
        ledger[root.root_id] = base_p

    roots[H_OTHER_ID] = RootHypothesis(
        root_id=H_OTHER_ID,
        statement="Other",
        exclusion_clause="Not explained by any named root",
        canonical_id=canonical_id_for_statement("Other"),
    )
    ledger[H_OTHER_ID] = gamma if count_named else 1.0

    enforce_absorber(ledger, [root.root_id for root in named_roots])
    return HypothesisSet(roots=roots, ledger=ledger)


def _required_slot_keys(request: SessionRequest) -> list[str]:
    required_slots = request.required_slots or []
    return [row["slot_key"] for row in required_slots if "slot_key" in row]


def _slots_missing(root: RootHypothesis, required_slot_keys: list[str]) -> bool:
    return any(slot_key not in root.obligations for slot_key in required_slot_keys)


def _node_statement_map(decomposition: Dict[str, str]) -> Dict[str, str]:
    return {
        "feasibility": decomposition.get("feasibility_statement", ""),
        "availability": decomposition.get("availability_statement", ""),
        "fit_to_key_features": decomposition.get("fit_statement", ""),
        "defeater_resistance": decomposition.get("defeater_statement", ""),
    }


def _decompose_root(
    root: RootHypothesis,
    required_slot_keys: list[str],
    decomposition: Dict[str, str],
    deps: RunSessionDeps,
) -> None:
    ok = bool(decomposition) and decomposition.get("ok", True)
    if not ok:
        root.k_root = min(root.k_root, 0.40)
        deps.audit_sink.append(
            AuditEvent(
                event_type="UNSCOPED_CAPPED",
                payload={"root_id": root.root_id, "k_root": root.k_root},
            )
        )
        return

    statement_map = _node_statement_map(decomposition)
    for slot_key in required_slot_keys:
        if slot_key in root.obligations:
            continue
        node_key = f"{root.root_id}:{slot_key}"
        statement = statement_map.get(slot_key) or ""
        root.obligations[slot_key] = Node(
            node_key=node_key,
            statement=statement,
            role="NEC",
            p=1.0,
            k=0.15,
        )
    root.status = "SCOPED"


def run_session(request: SessionRequest, deps: RunSessionDeps) -> SessionResult:
    hypothesis_set = _init_hypothesis_set(request)
    deps.audit_sink.append(
        AuditEvent(
            event_type="INVARIANT_SUM_TO_ONE_CHECK",
            payload={"total": sum(hypothesis_set.ledger.values())},
        )
    )

    required_slot_keys = _required_slot_keys(request)
    operation_log = []
    credits_remaining = request.credits
    total_credits_spent = 0
    named_roots = [
        root for root_id, root in hypothesis_set.roots.items() if root_id != H_OTHER_ID
    ]
    sorted_named_roots = sorted(named_roots, key=lambda root: root.canonical_id)
    target_root = sorted_named_roots[0] if sorted_named_roots else None

    while credits_remaining > 0 and target_root:
        credits_before = credits_remaining
        op_type = "DECOMPOSE"

        if target_root.status == "UNSCOPED" or _slots_missing(target_root, required_slot_keys):
            decomposition = deps.decomposer.decompose(target_root.root_id)
            _decompose_root(target_root, required_slot_keys, decomposition, deps)
        else:
            decomposition = deps.decomposer.decompose(target_root.root_id)
            _decompose_root(target_root, required_slot_keys, decomposition, deps)

        credits_remaining -= 1
        total_credits_spent += 1
        target_root.credits_spent += 1
        operation_log.append(
            {
                "op_type": op_type,
                "target_id": target_root.root_id,
                "credits_before": credits_before,
                "credits_after": credits_remaining,
            }
        )
        deps.audit_sink.append(
            AuditEvent(
                event_type="OP_EXECUTED",
                payload={
                    "op_type": op_type,
                    "target_id": target_root.root_id,
                    "credits_before": credits_before,
                    "credits_after": credits_remaining,
                },
            )
        )

    stop_reason = StopReason.CREDITS_EXHAUSTED if credits_remaining == 0 else None

    roots_view = {
        root_id: {
            "id": root.root_id,
            "statement": root.statement,
            "exclusion_clause": root.exclusion_clause,
            "canonical_id": root.canonical_id,
            "status": root.status,
            "k_root": root.k_root,
            "p_ledger": hypothesis_set.ledger.get(root_id, 0.0),
            "credits_spent": root.credits_spent,
            "obligations": {
                slot_key: {
                    "node_key": node.node_key,
                    "statement": node.statement,
                    "role": node.role,
                    "p": node.p,
                    "k": node.k,
                    "children": list(node.children),
                    "decomp_type": node.decomp_type,
                    "coupling": node.coupling,
                }
                for slot_key, node in root.obligations.items()
            },
        }
        for root_id, root in hypothesis_set.roots.items()
    }

    return SessionResult(
        roots=roots_view,
        ledger=hypothesis_set.ledger,
        audit=[{"event_type": event.event_type, "payload": event.payload} for event in deps.audit_sink.events],
        stop_reason=stop_reason,
        credits_remaining=credits_remaining,
        total_credits_spent=total_credits_spent,
        operation_log=operation_log,
    )
