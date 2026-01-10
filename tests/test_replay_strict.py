from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core import RootSpec, SessionConfig, SessionRequest, replay_session, run_session
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent


@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class ScriptDecomposer:
    def decompose(self, target_id: str) -> Dict[str, Any]:
        if ":" in target_id:
            return {
                "ok": True,
                "type": "AND",
                "coupling": 0.80,
                "children": [
                    {
                        "child_id": "c1",
                        "statement": f"{target_id} part1",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": "Check evidence for part1",
                        "overlap_with_siblings": [],
                    },
                    {
                        "child_id": "c2",
                        "statement": f"{target_id} part2",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": "Check evidence for part2",
                        "overlap_with_siblings": [],
                    },
                ],
            }
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}


@dataclass
class ScriptEvaluator:
    outcomes: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def evaluate(self, node_key: str) -> Dict[str, Any]:
        return self.outcomes.get(
            node_key,
            {
                "p": 0.75,
                "A": 2,
                "B": 1,
                "C": 1,
                "D": 1,
                "evidence_ids": ["EV-1"],
                "evidence_quality": "direct",
                "reasoning_summary": "Supported by EV-1.",
                "defeaters": ["No contradicting items seen."],
                "uncertainty_source": "Limited packet.",
                "assumptions": [],
            },
        )


def test_replay_matches_final_ledger_and_stop_reason() -> None:
    audit = MemAudit()
    deps = RunSessionDeps(evaluator=ScriptEvaluator(), decomposer=ScriptDecomposer(), audit_sink=audit)

    req = SessionRequest(
        scope="replay strict",
        roots=[
            RootSpec("H1", "Mechanism A", "x"),
            RootSpec("H2", "Mechanism B", "x"),
        ],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open"),
        credits=6,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_credits_exhausted",
        evidence_items=[{"id": "EV-1", "source": "test", "text": "Evidence item 1."}],
    )

    res = run_session(req, deps).to_dict_view()
    rep = replay_session(res["audit"]).to_dict_view()

    assert res["stop_reason"] == "CREDITS_EXHAUSTED"
    assert rep["stop_reason"] == "CREDITS_EXHAUSTED"

    for k, v in res["ledger"].items():
        assert abs(float(rep["ledger"].get(k, 0.0)) - float(v)) <= 1e-9

    assert abs(sum(rep["ledger"].values()) - 1.0) <= 1e-9
    assert len(rep["operation_log"]) == len(res["operation_log"])
