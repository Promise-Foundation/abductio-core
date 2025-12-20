from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import pytest

from abductio_core import RootSpec, SessionConfig, SessionRequest, replay_session, run_session
from abductio_core.adapters.openai_llm import OpenAIJsonClient, OpenAIDecomposerPort, OpenAIEvaluatorPort
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent


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
        evaluator=OpenAIEvaluatorPort(client, claim="E2E OpenAI ports", root_statements=root_statements),
        decomposer=OpenAIDecomposerPort(
            client,
            required_slots_hint=["feasibility"],
            claim="E2E OpenAI ports",
            root_statements=root_statements,
        ),
        audit_sink=InMemoryAudit(),
    )

    req = SessionRequest(
        claim="E2E OpenAI ports",
        roots=[
            RootSpec("H1", "Mechanism A", "x"),
            RootSpec("H2", "Mechanism B", "x"),
        ],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
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
    assert "SLOT_DECOMPOSED" in event_types
    assert "NODE_EVALUATED" in event_types
    assert "SOFT_AND_COMPUTED" in event_types
    assert "DAMPING_APPLIED" in event_types
    assert "STOP_REASON_RECORDED" in event_types

    rep = replay_session(res["audit"]).to_dict_view()
    for k, v in res["ledger"].items():
        assert abs(float(rep["ledger"].get(k, 0.0)) - float(v)) <= 1e-9
    assert rep["stop_reason"] == "CREDITS_EXHAUSTED"
