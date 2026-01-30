from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from abductio_core.application.dto import RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.use_cases import run_session as rs
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.canonical import canonical_id_for_statement
from abductio_core.domain.model import Node, RootHypothesis
from tests.support.noop_searcher import NoopSearcher


@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


@dataclass
class NoopDecomposer:
    def decompose(self, target_id: str) -> Dict[str, Any]:
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}


@dataclass
class ChildDecomposer:
    def decompose(self, target_id: str) -> Dict[str, Any]:
        if ":" in target_id:
            return {
                "ok": True,
                "type": "AND",
                "coupling": 0.80,
                "children": [
                    {"child_id": "c1", "statement": "child 1", "role": "NEC"},
                    {"child_id": "c2", "statement": "child 2", "role": "NEC"},
                ],
            }
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}


@dataclass
class NoopEvaluator:
    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: List[Any] | None = None,
    ) -> Dict[str, Any]:
        return {}


def _deps() -> RunSessionDeps:
    return RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )


def _base_request() -> SessionRequest:
    return SessionRequest(
        scope="test",
        roots=[RootSpec("H1", "Mechanism A", "x")],
        config=SessionConfig(tau=0.7, epsilon=0.05, gamma_noa=0.10, gamma_und=0.10, alpha=0.4, beta=1.0, W=3.0, lambda_voi=0.1, world_mode="open", gamma=0.2),
        credits=1,
        required_slots=None,
        run_mode="start_only",
    )


def test_validate_request_errors() -> None:
    req = _base_request()
    with pytest.raises(ValueError):
        rs._validate_request(req.__class__(**{**req.__dict__, "credits": -1}))
    with pytest.raises(ValueError):
        rs._validate_request(
            req.__class__(
                **{
                    **req.__dict__,
                    "config": SessionConfig(
                        tau=1.2,
                        epsilon=0.1,
                        gamma_noa=0.1,
                        gamma_und=0.1,
                        alpha=0.3,
                        beta=1.0,
                        W=3.0,
                        lambda_voi=0.1,
                        world_mode="open",
                        gamma=0.2,
                    ),
                }
            )
        )
    with pytest.raises(ValueError):
        rs._validate_request(
            req.__class__(**{**req.__dict__, "roots": [RootSpec("", "S", "x")]})
        )
    with pytest.raises(ValueError):
        rs._validate_request(
            req.__class__(**{**req.__dict__, "roots": [RootSpec("H1", "", "x")]})
        )
    with pytest.raises(ValueError):
        rs._validate_request(
            req.__class__(**{**req.__dict__, "required_slots": [{"slot_key": ""}]})
        )


def test_aggregate_soft_and_no_assessed_children() -> None:
    slot = Node(node_key="H1:fit_to_key_features", statement="fit", role="NEC", coupling=0.5)
    child_key = "H1:fit_to_key_features:c1"
    slot.children = [child_key]
    nodes = {child_key: Node(node_key=child_key, statement="child", role="NEC", assessed=False)}
    value, details = rs._aggregate_soft_and(slot, nodes)
    assert value == 0.5
    assert details["p_min"] == 0.5
    assert details["p_prod"] == 0.5


def test_apply_node_decomposition_branches() -> None:
    audit = MemAudit()
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=audit,
        searcher=NoopSearcher(),
    )
    nodes: Dict[str, Node] = {}
    assert rs._apply_node_decomposition(deps, "missing", {}, nodes) is False

    nodes["H1:slot"] = Node(node_key="H1:slot", statement="", role="NEC")
    assert rs._apply_node_decomposition(deps, "H1:slot", {}, nodes) is False
    assert nodes["H1:slot"].decomp_type == "NONE"
    assert any(e.event_type == "NODE_REFINED_REQUIREMENTS" for e in audit.events)

    audit.events.clear()
    decomp = {
        "type": "AND",
        "coupling": 0.8,
        "children": ["bad", {"id": ""}, {"child_id": "c1", "statement": "ok"}],
    }
    assert rs._apply_node_decomposition(deps, "H1:slot", decomp, nodes) is True
    canonical_child = canonical_id_for_statement("ok")
    assert f"H1:slot:{canonical_child}" in nodes


def test_select_helpers_cover_empty_and_assessed() -> None:
    root = RootHypothesis(root_id="H1", statement="S", exclusion_clause="x", canonical_id="cid")
    assert rs._select_slot_lowest_k(root, ["feasibility"], {}, 0.7) is None

    slot = Node(node_key="H1:slot", statement="", role="NEC")
    slot.children = ["c_missing"]
    assert rs._select_child_to_evaluate(slot, {}) is None

    child_nodes = {"c1": Node(node_key="c1", statement="", role="NEC", assessed=True)}
    slot.children = ["c1"]
    assert rs._select_child_to_evaluate(slot, child_nodes) is None

    nodes = {"H1:slot": slot}
    root.obligations["slot"] = "H1:slot"
    assert rs._select_child_for_evaluation(root, [], nodes) is None
    assert rs._select_child_for_evaluation(root, ["slot"], nodes) is None

    assert rs._select_slot_for_evaluation(root, [], nodes) is None
    assert rs._select_slot_for_evaluation(RootHypothesis("H2", "S", "x", "cid2"), ["slot"], nodes) is None


def test_run_session_evaluation_with_missing_node() -> None:
    req = _base_request()
    req = req.__class__(**{**req.__dict__, "run_mode": "evaluation", "run_target": "H1:missing"})
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "CREDITS_EXHAUSTED"


def test_run_session_pre_scoped_missing_root_and_op_limit_zero() -> None:
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "pre_scoped_roots": ["H_missing"],
            "run_mode": "operations",
            "run_count": 0,
            "credits": 3,
        }
    )
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "OP_LIMIT_REACHED"


def test_evaluation_mode_no_slots_no_legal_op() -> None:
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluation",
            "run_target": None,
            "credits": 2,
        }
    )
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"


def test_frontier_confident_and_legal_next_helpers() -> None:
    root = RootHypothesis(root_id="H1", statement="S", exclusion_clause="x", canonical_id="cid", status="SCOPED")
    nodes: Dict[str, Node] = {}
    assert rs._frontier_confident([], ["slot"], nodes, 0.7) is False
    assert rs._frontier_confident([root], ["slot"], nodes, 0.7) is False
    nodes["H1:slot"] = Node(node_key="H1:slot", statement="", role="NEC", k=0.5, assessed=True)
    root.obligations["slot"] = "H1:slot"
    assert rs._frontier_confident([root], ["slot"], nodes, 0.7) is False
    nodes["H1:slot"].k = 0.8
    assert rs._frontier_confident([root], ["slot"], nodes, 0.7) is True

    root.status = "UNSCOPED"
    nxt = rs._legal_next_for_root(root, ["slot"], 0.7, nodes, credits_left=2)
    assert nxt == ("DECOMPOSE", "H1")

    root.status = "SCOPED"
    root.obligations.clear()
    nxt = rs._legal_next_for_root(root, ["slot"], 0.7, nodes, credits_left=2)
    assert nxt == ("DECOMPOSE", "H1")

    nxt = rs._legal_next_for_root(root, [], 0.7, nodes, credits_left=2)
    assert nxt is None

    nodes["H1:slot"] = Node(node_key="H1:slot", statement="", role="NEC", k=0.1, assessed=False)
    root.obligations["slot"] = "H1:slot"
    nxt = rs._legal_next_for_root(root, ["slot"], 0.7, nodes, credits_left=2)
    assert nxt == ("DECOMPOSE", "H1:slot")

    nodes["H1:slot"].decomp_type = "NONE"
    nxt = rs._legal_next_for_root(root, ["slot"], 0.7, nodes, credits_left=1)
    assert nxt == ("EVALUATE", "H1:slot")


def test_decompose_root_skips_existing_slot() -> None:
    audit = MemAudit()
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=audit,
        searcher=NoopSearcher(),
    )
    root = RootHypothesis(root_id="H1", statement="S", exclusion_clause="x", canonical_id="cid")
    nodes: Dict[str, Node] = {"H1:feasibility": Node(node_key="H1:feasibility", statement="existing", role="NEC")}
    root.obligations["feasibility"] = "H1:feasibility"
    rs._decompose_root(
        deps,
        root,
        ["feasibility"],
        {"feasibility": "NEC"},
        {"ok": True, "feasibility_statement": "new"},
        None,
        {},
        nodes,
    )
    assert nodes["H1:feasibility"].statement == "existing"


def test_select_slot_for_evaluation_returns_node_key() -> None:
    root = RootHypothesis(root_id="H1", statement="S", exclusion_clause="x", canonical_id="cid", status="SCOPED")
    nodes = {"H1:feasibility": Node(node_key="H1:feasibility", statement="", role="NEC", assessed=False)}
    root.obligations["feasibility"] = "H1:feasibility"
    assert rs._select_slot_for_evaluation(root, ["feasibility"], nodes) == "H1:feasibility"


def test_evaluation_mode_continues_to_next_root() -> None:
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "roots": [RootSpec("H1", "Mechanism A", "x"), RootSpec("H2", "Mechanism B", "x")],
            "run_mode": "evaluation",
            "run_target": None,
            "credits": 1,
            "pre_scoped_roots": ["H2"],
        }
    )
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "CREDITS_EXHAUSTED"
    assert res["total_credits_spent"] == 1


def test_evaluations_children_continue_then_evaluate_slot() -> None:
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "roots": [RootSpec("H1", "Mechanism A", "x"), RootSpec("H2", "Mechanism B", "x")],
            "run_mode": "evaluations_children",
            "run_count": 2,
            "credits": 1,
            "pre_scoped_roots": ["H2"],
        }
    )
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["total_credits_spent"] == 1


def test_evaluations_children_no_slots_stops() -> None:
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 1,
            "credits": 1,
            "pre_scoped_roots": [],
        }
    )
    res = rs.run_session(req, _deps()).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"


def test_evaluations_children_selected_slot_none_stops(monkeypatch) -> None:
    def _none_slot(*args, **kwargs):
        return None

    monkeypatch.setattr(rs, "_select_slot_lowest_k", _none_slot)
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 1,
            "credits": 1,
            "pre_scoped_roots": ["H1"],
        }
    )
    res = rs.run_session(req, deps).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"


def test_evaluations_children_slot_missing_continues(monkeypatch) -> None:
    calls = {"count": 0}

    def _fake_slot(*args, **kwargs):
        if calls["count"] == 0:
            calls["count"] += 1
            return "missing"
        return "availability"

    monkeypatch.setattr(rs, "_select_slot_lowest_k", _fake_slot)
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 2,
            "credits": 1,
            "pre_scoped_roots": ["H1"],
        }
    )
    res = rs.run_session(req, deps).to_dict_view()
    assert res["total_credits_spent"] == 1


def test_evaluations_children_slot_missing_all_roots_stop(monkeypatch) -> None:
    class FlakyObligations:
        def __init__(self, node_key: str) -> None:
            self._node_key = node_key
            self._count = 0

        def __contains__(self, key: object) -> bool:
            if key != "feasibility":
                return False
            self._count += 1
            return self._count <= 2

        def __getitem__(self, key: str) -> str:
            return self._node_key

        def get(self, key: str, default=None) -> Optional[str]:
            return None
        def items(self):
            return []
        def values(self):
            return []

    def _missing_slot(*args, **kwargs):
        return "missing"

    monkeypatch.setattr(rs, "_select_slot_lowest_k", _missing_slot)

    root = RootHypothesis(root_id="H1", statement="S", exclusion_clause="x", canonical_id="cid", status="SCOPED")
    root.obligations = FlakyObligations("H1:feasibility")  # type: ignore[assignment]
    hset = rs.HypothesisSet(
        roots={
            "H1": root,
            "H_NOA": RootHypothesis("H_NOA", "None of the above", "", "cid2"),
            "H_UND": RootHypothesis("H_UND", "Underdetermined", "", "cid3"),
        },
        ledger={"H1": 1.0, "H_NOA": 0.0, "H_UND": 0.0},
    )

    def _fake_init(_request):
        return hset

    monkeypatch.setattr(rs, "_init_hypothesis_set", _fake_init)
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=NoopDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 1,
            "credits": 1,
            "pre_scoped_roots": [],
        }
    )
    res = rs.run_session(req, deps).to_dict_view()
    assert res["stop_reason"] == "NO_LEGAL_OP"


def test_evaluations_children_credits_exhausted_inside_loop() -> None:
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=ChildDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 2,
            "credits": 1,
            "pre_scoped_roots": ["H1"],
        }
    )
    res = rs.run_session(req, deps).to_dict_view()
    assert res["stop_reason"] == "CREDITS_EXHAUSTED"
    assert res["total_credits_spent"] == 1


def test_evaluations_children_op_limit_reached_inside_loop() -> None:
    deps = RunSessionDeps(
        evaluator=NoopEvaluator(),
        decomposer=ChildDecomposer(),
        audit_sink=MemAudit(),
        searcher=NoopSearcher(),
    )
    req = _base_request()
    req = req.__class__(
        **{
            **req.__dict__,
            "run_mode": "evaluations_children",
            "run_count": 1,
            "credits": 2,
            "pre_scoped_roots": ["H1"],
        }
    )
    res = rs.run_session(req, deps).to_dict_view()
    assert res["stop_reason"] == "OP_LIMIT_REACHED"
