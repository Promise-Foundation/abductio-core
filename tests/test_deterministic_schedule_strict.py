from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.application.canonical import canonical_id_for_statement
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
                    {"child_id": "c1", "statement": f"{target_id} p1", "role": "NEC"},
                    {"child_id": "c2", "statement": f"{target_id} p2", "role": "NEC"},
                ],
            }
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}


@dataclass
class ScriptEvaluator:
    def evaluate(self, node_key: str) -> Dict[str, Any]:
        return {"p": 0.80, "A": 2, "B": 1, "C": 1, "D": 1, "evidence_refs": "ref1"}


def _run(roots: List[RootSpec]) -> Dict[str, Any]:
    audit = MemAudit()
    deps = RunSessionDeps(evaluator=ScriptEvaluator(), decomposer=ScriptDecomposer(), audit_sink=audit)
    req = SessionRequest(
        scope="determinism strict",
        roots=roots,
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
        credits=8,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_credits_exhausted",
    )
    return run_session(req, deps).to_dict_view()


def test_operation_sequence_invariant_under_root_order() -> None:
    roots_a = [
        RootSpec("H1", "Alpha mechanism", "x"),
        RootSpec("H2", "Beta mechanism", "x"),
        RootSpec("H3", "Gamma mechanism", "x"),
    ]
    roots_b = list(reversed(roots_a))

    res_a = _run(roots_a)
    res_b = _run(roots_b)

    canon = {r["id"]: canonical_id_for_statement(r["statement"]) for r in res_a["roots"].values() if r["id"] != "H_other"}

    def normalize(op: Dict[str, Any]) -> str:
        tid = str(op["target_id"])
        if ":" not in tid and tid in canon:
            return canon[tid]
        return tid

    seq_a = [normalize(op) for op in res_a["operation_log"]]
    seq_b = [normalize(op) for op in res_b["operation_log"]]
    assert seq_a == seq_b
