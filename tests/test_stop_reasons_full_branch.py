from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent


@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class NoChildrenDecomposer:
    """Scopes roots but never produces slot children."""

    def decompose(self, target_id: str) -> Dict[str, Any]:
        if ":" in target_id:
            return {"ok": True, "type": "AND", "coupling": 0.80, "children": []}
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}


@dataclass
class LowConfidenceEvaluator:
    """Produces k=0.15 so FRONTIER_CONFIDENT cannot trigger."""

    def evaluate(self, node_key: str) -> Dict[str, Any]:
        return {"p": 0.9, "A": 1, "B": 0, "C": 0, "D": 0, "evidence_refs": "ref1"}


def _deps() -> RunSessionDeps:
    return RunSessionDeps(
        evaluator=LowConfidenceEvaluator(),
        decomposer=NoChildrenDecomposer(),
        audit_sink=MemAudit(),
    )


def test_stop_reason_no_hypotheses_when_no_named_roots() -> None:
    req = SessionRequest(
        scope="no hypotheses",
        roots=[],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
        credits=5,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_stops",
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_HYPOTHESES"


def test_stop_reason_op_limit_reached() -> None:
    req = SessionRequest(
        scope="op limit",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
        credits=10,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="operations",
        run_count=1,
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "OP_LIMIT_REACHED"
    assert res["total_credits_spent"] == 1


def test_stop_reason_no_legal_op_after_decomp_and_eval() -> None:
    req = SessionRequest(
        scope="no legal op",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
        credits=10,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_stops",
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"
