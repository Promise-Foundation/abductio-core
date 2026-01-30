from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import pytest

from abductio_core import RootSpec, SessionConfig, SessionRequest, replay_session, run_session
from abductio_core.adapters.openai_llm import OpenAIJsonClient, OpenAIDecomposerPort, OpenAIEvaluatorPort
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent
from tests.support.noop_searcher import NoopSearcher


@dataclass
class InMemoryAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.mark.e2e
def test_e2e_openai_scopes_decomposes_evaluates_and_replays() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAIJsonClient(model=model, temperature=0.0)
    root_statements = {"H1": "Mechanism A", "H2": "Mechanism B"}

    required_slots = [{"slot_key": "feasibility", "role": "NEC"}]
    deps = RunSessionDeps(
        evaluator=OpenAIEvaluatorPort(client, scope="E2E OpenAI ports", root_statements=root_statements),
        decomposer=OpenAIDecomposerPort(
            client,
            required_slots_hint=["feasibility"],
            scope="E2E OpenAI ports",
            root_statements=root_statements,
        ),
        audit_sink=InMemoryAudit(),
        searcher=NoopSearcher(),
    )

    req = SessionRequest(
        scope="E2E OpenAI ports",
        roots=[
            RootSpec("H1", "Mechanism A", "x"),
            RootSpec("H2", "Mechanism B", "x"),
        ],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.20),
        credits=6,
        required_slots=required_slots,
        run_mode="until_credits_exhausted",
    )

    res = run_session(req, deps).to_dict_view()
    assert abs(sum(res["ledger"].values()) - 1.0) <= 1e-9
    assert res["stop_reason"] == "CREDITS_EXHAUSTED"
    assert any(op["op_type"] == "DECOMPOSE" for op in res["operation_log"])
    assert any(op["op_type"] == "EVALUATE" for op in res["operation_log"])

    event_types = [event["event_type"] for event in res["audit"]]
    assert "ROOT_SCOPED" in event_types
    assert "NODE_REFINED_REQUIREMENTS" in event_types
    assert "NODE_EVALUATED" in event_types
    assert "SOFT_AND_COMPUTED" in event_types
    assert "DAMPING_APPLIED" in event_types
    assert "STOP_REASON_RECORDED" in event_types

    rep = replay_session(res["audit"]).to_dict_view()
    for k, v in res["ledger"].items():
        assert abs(float(rep["ledger"].get(k, 0.0)) - float(v)) <= 1e-9
    assert rep["stop_reason"] == "CREDITS_EXHAUSTED"
