from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from abductio_core.application.dto import EvidenceItem, RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.use_cases.run_session import run_session
from abductio_core.domain.audit import AuditEvent


@dataclass
class RecordingEvaluator:
    seen_evidence: List[EvidenceItem] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.seen_evidence is None:
            self.seen_evidence = []

    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: List[EvidenceItem] | None = None,
    ) -> Dict[str, Any]:
        self.seen_evidence = list(evidence_items or [])
        return {
            "p": 0.8,
            "A": 2,
            "B": 1,
            "C": 1,
            "D": 1,
            "evidence_ids": ["S1"],
            "evidence_quality": "direct",
            "reasoning_summary": "Supported by S1.",
            "defeaters": ["None noted."],
            "uncertainty_source": "Test.",
            "assumptions": [],
        }


@dataclass
class NoopDecomposer:
    def decompose(self, target_id: str) -> Dict[str, Any]:
        return {"ok": True}


@dataclass
class DeterministicSearcher:
    def search(self, query: str, *, limit: int, metadata: Dict[str, Any]) -> List[EvidenceItem]:
        return [
            EvidenceItem(
                id="S1",
                source="search",
                text=f"Search evidence for {query}",
                location={"query": query},
                metadata={"depth": metadata.get("depth")},
            )
        ][:limit]


@dataclass
class MemAudit:
    events: List[AuditEvent]

    def __init__(self) -> None:
        self.events = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def test_search_adds_evidence_and_packet_hash() -> None:
    audit = MemAudit()
    evaluator = RecordingEvaluator()
    deps = RunSessionDeps(
        evaluator=evaluator,
        decomposer=NoopDecomposer(),
        audit_sink=audit,
        searcher=DeterministicSearcher(),
    )

    req = SessionRequest(
        scope="search packet test",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(
            tau=0.0,
            epsilon=0.05,
            gamma_noa=0.10,
            gamma_und=0.10,
            alpha=0.4,
            beta=1.0,
            W=3.0,
            lambda_voi=0.1,
            world_mode="open",
            rho_eval_min=0.5,
            gamma=0.2,
        ),
        credits=2,
        required_slots=[{"slot_key": "availability", "role": "NEC"}],
        run_mode="until_credits_exhausted",
        search_enabled=True,
        max_search_depth=0,
        max_search_per_node=1,
        pre_scoped_roots=["H1"],
    )

    result = run_session(req, deps).to_dict_view()
    search_events = [e for e in result["audit"] if e["event_type"] == "SEARCH_EXECUTED"]
    assert search_events, "Expected at least one SEARCH_EXECUTED event"
    payload = search_events[0]["payload"]
    assert payload.get("search_snapshot_hash")
    assert payload.get("evidence_packet_hash")
    assert "S1" in payload.get("new_evidence_ids", [])

    seen_ids = {item.id for item in evaluator.seen_evidence}
    assert "S1" in seen_ids
