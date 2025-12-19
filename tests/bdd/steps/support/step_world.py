"""Scenario state for Behave step definitions.

This stays within the application layer so steps do not reach into domain
or infrastructure code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from behave.exceptions import Pending

from abductio_core.application.dto import RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.result import SessionResult
from abductio_core.application.use_cases.run_session import run_session
from tests.bdd.steps.support.deterministic_decomposer import DeterministicDecomposer
from tests.bdd.steps.support.deterministic_evaluator import DeterministicEvaluator
from tests.bdd.steps.support.in_memory_audit import InMemoryAuditSink


@dataclass
class StepWorld:
    config: Dict[str, Any] = field(default_factory=dict)
    required_slots: List[Dict[str, Any]] = field(default_factory=list)
    roots: List[Dict[str, Any]] = field(default_factory=list)
    roots_a: List[Dict[str, Any]] = field(default_factory=list)
    roots_b: List[Dict[str, Any]] = field(default_factory=list)
    decomposer_script: Dict[str, Any] = field(default_factory=dict)
    evaluator_script: Dict[str, Any] = field(default_factory=dict)
    credits: Optional[int] = None
    ledger: Dict[str, float] = field(default_factory=dict)
    epsilon_override: Optional[float] = None
    audit_trace: List[Dict[str, Any]] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    replay_result: Optional[Dict[str, Any]] = None
    rubric: Dict[str, int] = field(default_factory=dict)
    derived_k: Optional[float] = None

    def mark_pending(self, message: str) -> None:
        raise Pending(message)

    def set_config(self, values: Dict[str, str]) -> None:
        self.config = {key: float(value) for key, value in values.items()}

    def set_required_slots(self, table: List[Dict[str, str]]) -> None:
        self.required_slots = table

    def set_roots(self, table: List[Dict[str, str]]) -> None:
        self.roots = table

    def set_roots_a(self, table: List[Dict[str, str]]) -> None:
        self.roots_a = table

    def set_roots_b(self, table: List[Dict[str, str]]) -> None:
        self.roots_b = table

    def set_credits(self, credits: int) -> None:
        self.credits = credits

    def set_decomposer_scope_roots(self, table: Optional[List[Dict[str, str]]] = None) -> None:
        self.decomposer_script["scope_roots"] = table or "all"

    def set_decomposer_fail_root(self, root_id: str) -> None:
        self.decomposer_script.setdefault("fail_roots", set()).add(root_id)

    def set_decomposer_slot_decomposition(
        self,
        slot_key: str,
        decomp_type: str,
        coupling: Optional[float],
        children: List[Dict[str, str]],
    ) -> None:
        self.decomposer_script.setdefault("slot_decompositions", {})[slot_key] = {
            "type": decomp_type,
            "coupling": coupling,
            "children": children,
        }

    def set_evaluator_outcome(self, node_key: str, outcome: Dict[str, Any]) -> None:
        self.evaluator_script.setdefault("outcomes", {})[node_key] = outcome

    def set_evaluator_outcomes(self, table: List[Dict[str, str]]) -> None:
        outcomes: Dict[str, Dict[str, Any]] = {}
        for row in table:
            node_key = row.get("node_key") or row.get("node")
            if not node_key:
                continue
            outcomes[node_key] = row
        self.evaluator_script["outcomes"] = outcomes

    def set_rubric(self, rubric: Dict[str, int]) -> None:
        self.rubric = rubric

    def set_ledger(self, table: List[Dict[str, str]]) -> None:
        self.ledger = {row["id"]: float(row["p_ledger"]) for row in table}

    def set_epsilon(self, epsilon: float) -> None:
        self.epsilon_override = epsilon

    def set_scoped_root(self, root_id: str) -> None:
        self.decomposer_script.setdefault("scoped_roots", set()).add(root_id)

    def set_slot_initial_p(self, node_key: str, p_value: float) -> None:
        self.decomposer_script.setdefault("slot_initial_p", {})[node_key] = p_value

    def set_child_evaluated(self, child_id: str, p_value: float, evidence_refs: str) -> None:
        self.evaluator_script.setdefault("child_evaluations", {})[child_id] = {
            "p": p_value,
            "evidence_refs": evidence_refs,
        }

    def run_engine(self, mode: str) -> None:
        if mode.startswith("start_session:"):
            claim = mode.split(":", 1)[1]
            roots = self.roots
        elif mode == "until_credits_exhausted":
            claim = self.config.get("claim", "Untitled claim")
            roots = self.roots
        elif mode == "until_stops":
            claim = self.config.get("claim", "Untitled claim")
            roots = self.roots
        elif mode == "run_set_a":
            claim = self.config.get("claim", "Untitled claim")
            roots = self.roots_a
        elif mode == "run_set_b":
            claim = self.config.get("claim", "Untitled claim")
            roots = self.roots_b
        else:
            self.mark_pending(f"Engine execution not implemented for mode: {mode}")
            return

        session_request = self._build_request(claim, roots)
        deps = self._build_deps()
        result = run_session(session_request, deps)
        result_view = result.to_dict_view()
        if mode == "run_set_b":
            self.replay_result = result_view
        else:
            self.result = result_view

    def derive_k_from_rubric(self) -> None:
        self.mark_pending("k-derivation policy not implemented")

    def _build_request(self, claim: str, roots: List[Dict[str, Any]]) -> SessionRequest:
        config = SessionConfig(
            tau=float(self.config.get("tau", 0.0)),
            epsilon=float(self.config.get("epsilon", 0.0)),
            gamma=float(self.config.get("gamma", 0.0)),
            alpha=float(self.config.get("alpha", 0.0)),
        )
        root_specs = [
            RootSpec(
                root_id=row["id"],
                statement=row["statement"],
                exclusion_clause=row.get("exclusion_clause", ""),
            )
            for row in roots
        ]
        credits = int(self.credits or 0)
        return SessionRequest(
            claim=claim,
            roots=root_specs,
            config=config,
            credits=credits,
            required_slots=self.required_slots,
        )

    def _build_deps(self) -> RunSessionDeps:
        evaluator = DeterministicEvaluator(self.evaluator_script)
        decomposer = DeterministicDecomposer(self.decomposer_script)
        audit_sink = InMemoryAuditSink()
        return RunSessionDeps(
            evaluator=evaluator,
            decomposer=decomposer,
            audit_sink=audit_sink,
        )
