from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent
from tests.support.noop_searcher import NoopSearcher


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

    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: List[Any] | None = None,
    ) -> Dict[str, Any]:
        return {
            "p": 0.9,
            "A": 1,
            "B": 0,
            "C": 0,
            "D": 0,
            "evidence_ids": ["EV-1"],
            "evidence_quality": "direct",
            "reasoning_summary": "Supported by EV-1.",
            "defeaters": ["No direct defeaters observed."],
            "uncertainty_source": "Sparse evidence packet.",
            "assumptions": [],
        }


def _deps() -> RunSessionDeps:
    return RunSessionDeps(
        evaluator=LowConfidenceEvaluator(),
        decomposer=NoChildrenDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )


def test_stop_reason_no_hypotheses_when_no_named_roots() -> None:
    req = SessionRequest(
        scope="no hypotheses",
        roots=[],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.20),
        credits=5,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_stops",
        evidence_items=[{"id": "EV-1", "source": "test", "text": "Evidence item 1."}],
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_HYPOTHESES"


def test_stop_reason_op_limit_reached() -> None:
    req = SessionRequest(
        scope="op limit",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.20),
        credits=10,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="operations",
        run_count=1,
        evidence_items=[{"id": "EV-1", "source": "test", "text": "Evidence item 1."}],
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "OP_LIMIT_REACHED"
    assert res["total_credits_spent"] == 1


def test_stop_reason_no_legal_op_after_decomp_and_eval() -> None:
    req = SessionRequest(
        scope="no legal op",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.20),
        credits=10,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_stops",
        evidence_items=[{"id": "EV-1", "source": "test", "text": "Evidence item 1."}],
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"


def test_stop_reason_mece_certificate_failed_before_spending_credits() -> None:
    req = SessionRequest(
        scope="mece cert fail",
        roots=[
            RootSpec("H1", "Mechanism A", "x"),
            RootSpec("H2", "Mechanism B", "x"),
        ],
        config=SessionConfig(
            tau=0.70,
            epsilon=0.05,
            gamma_noa=0.10,
            gamma_und=0.10,
            alpha=0.40,
            beta=1.0,
            W=3.0,
            lambda_voi=0.1,
            world_mode="open",
            gamma=0.20,
        ),
        credits=10,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_stops",
        strict_mece=True,
        max_pair_overlap=0.0,
        mece_certificate={
            "pairwise_overlaps": {"H1|H2": 2.0},
            "pairwise_discriminators": {"H1|H2": "Differentiator exists"},
        },
        evidence_items=[{"id": "EV-1", "source": "test", "text": "Evidence item 1."}],
    )
    res = run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "MECE_CERTIFICATE_FAILED"
    assert res["total_credits_spent"] == 0
    assert res["operation_log"] == []
    checks = [event for event in res["audit"] if event.get("event_type") == "MECE_CERTIFICATE_CHECKED"]
    assert checks
    assert checks[-1]["payload"].get("status") == "FAILED"
