from __future__ import annotations

import os

import pytest

from abductio_core.application.dto import RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.use_cases.run_session import run_session
from tests.support.noop_searcher import NoopSearcher


@pytest.mark.e2e
def test_e2e_llm_integration_smoke_realistic_usage() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
    pytest.importorskip("openai")

    from abductio_core.adapters.openai_llm import (
        OpenAIDecomposerPort,
        OpenAIEvaluatorPort,
        OpenAIJsonClient,
    )

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAIJsonClient(model=model, temperature=0.0)
    root_statements = {"H1": "Mechanism A", "H2": "Mechanism B"}

    deps = RunSessionDeps(
        evaluator=OpenAIEvaluatorPort(client, scope="E2E smoke: abductio-core with real LLM ports", root_statements=root_statements),
        decomposer=OpenAIDecomposerPort(
            client,
            required_slots_hint=["feasibility"],
            scope="E2E smoke: abductio-core with real LLM ports",
            root_statements=root_statements,
        ),
        audit_sink=_InMemoryAuditSink(),
        searcher=NoopSearcher(),
    )

    request = SessionRequest(
        scope="E2E smoke: abductio-core with real LLM ports",
        roots=[
            RootSpec(root_id="H1", statement="Mechanism A", exclusion_clause="Not explained by any other root"),
            RootSpec(root_id="H2", statement="Mechanism B", exclusion_clause="Not explained by any other root"),
        ],
        config=SessionConfig(tau=0.70, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.40, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.20),
        credits=6,
        required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
        run_mode="until_credits_exhausted",
    )

    result = run_session(request, deps)
    view = result.to_dict_view()

    assert "roots" in view
    assert "ledger" in view
    assert "audit" in view
    assert "operation_log" in view
    assert "H_NOA" in view["roots"]
    assert "H_UND" in view["roots"]
    assert abs(sum(view["ledger"].values()) - 1.0) <= 1e-9

    named_roots = [rid for rid in view["roots"] if rid not in {"H_NOA", "H_UND"}]
    assert set(named_roots) == {"H1", "H2"}
    for root_id in named_roots:
        root = view["roots"][root_id]
        assert root["canonical_id"]
        assert root["status"] in {"SCOPED", "UNSCOPED"}
        assert "obligations" in root

    op_types = [op["op_type"] for op in view["operation_log"]]
    assert "DECOMPOSE" in op_types
    assert "EVALUATE" in op_types

    feasibility_ps = []
    feasibility_ks = []
    for root_id in named_roots:
        root = view["roots"][root_id]
        node = root.get("obligations", {}).get("feasibility")
        if node:
            feasibility_ps.append(float(node["p"]))
            feasibility_ks.append(float(node["k"]))

    assert feasibility_ps, "expected feasibility nodes to exist"
    assert any(p != 1.0 for p in feasibility_ps), "expected at least one feasibility p to move from neutral"
    for p in feasibility_ps:
        assert 0.0 <= p <= 1.0
    for k in feasibility_ks:
        assert 0.15 <= k <= 0.90

    event_types = [event["event_type"] for event in view["audit"]]
    assert "OP_EXECUTED" in event_types
    assert "OPEN_WORLD_RESIDUALS_ENFORCED" in event_types or "OTHER_ABSORBER_ENFORCED" in event_types
    assert "INVARIANT_SUM_TO_ONE_CHECK" in event_types
    assert "STOP_REASON_RECORDED" in event_types


class _InMemoryAuditSink:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:
        self.events.append(event)
