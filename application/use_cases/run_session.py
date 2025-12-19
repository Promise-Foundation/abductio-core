from __future__ import annotations

from typing import Dict

from application.dto import RootSpec, SessionRequest
from application.result import SessionResult, StopReason
from application.ports import RunSessionDeps
from domain.audit import AuditEvent
from domain.canonical import canonical_id_for_statement
from domain.invariants import H_OTHER_ID, enforce_absorber
from domain.model import HypothesisSet, RootHypothesis


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


def run_session(request: SessionRequest, deps: RunSessionDeps) -> SessionResult:
    hypothesis_set = _init_hypothesis_set(request)
    deps.audit_sink.append(
        AuditEvent(
            event_type="INVARIANT_SUM_TO_ONE_CHECK",
            payload={"total": sum(hypothesis_set.ledger.values())},
        )
    )

    stop_reason = None
    if request.credits == 0:
        stop_reason = StopReason.CREDITS_EXHAUSTED

    roots_view = {
        root_id: {
            "id": root.root_id,
            "statement": root.statement,
            "exclusion_clause": root.exclusion_clause,
            "canonical_id": root.canonical_id,
            "status": root.status,
            "k_root": root.k_root,
        }
        for root_id, root in hypothesis_set.roots.items()
    }

    return SessionResult(
        roots=roots_view,
        ledger=hypothesis_set.ledger,
        audit=[{"event_type": event.event_type, "payload": event.payload} for event in deps.audit_sink.events],
        stop_reason=stop_reason,
        credits_remaining=request.credits,
        total_credits_spent=0,
        operation_log=[],
    )
