"""Scenario state for Behave step definitions.

This stays within the application layer so steps do not reach into domain
or infrastructure code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from behave import Pending  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - fallback for behave versions without Pending
    class Pending(RuntimeError):
        """Fallback pending exception for Behave versions without Pending."""

from abductio_core.application.dto import RootSpec, SessionConfig, SessionRequest
from abductio_core.domain.canonical import canonical_id_for_statement
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
    guardrail_applied: bool = False
    initial_ledger: Dict[str, float] = field(default_factory=dict)
    child_id_map: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def mark_pending(self, message: str) -> None:
        raise Pending(message)

    def set_config(self, values: Dict[str, str]) -> None:
        parsed: Dict[str, Any] = {}
        for key, value in values.items():
            try:
                parsed[key] = float(value)
            except (TypeError, ValueError):
                parsed[key] = str(value)
        self.config = parsed

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
        fail_roots = set(self.decomposer_script.get("fail_roots", set()))
        fail_roots.add(root_id)
        self.decomposer_script["fail_roots"] = fail_roots
        self.decomposer_script["force_scope_fail_root"] = root_id

    def set_decomposer_slot_decomposition(
        self,
        slot_key: str,
        decomp_type: str,
        coupling: Optional[float],
        children: List[Dict[str, str]],
    ) -> None:
        mapped_children = []
        slot_map = self.child_id_map.setdefault(slot_key, {})
        for child in children:
            statement = str(child.get("statement", ""))
            alias = str(child.get("child_id") or child.get("id") or "")
            canonical = canonical_id_for_statement(statement) if statement else alias
            if alias:
                slot_map[alias] = canonical
            mapped = dict(child)
            mapped.setdefault("falsifiable", True)
            mapped.setdefault("test_procedure", "Check evidence for child statement")
            mapped.setdefault("overlap_with_siblings", [])
            mapped["child_id"] = canonical
            mapped.pop("id", None)
            mapped_children.append(mapped)
        self.decomposer_script.setdefault("slot_decompositions", {})[slot_key] = {
            "type": decomp_type,
            "coupling": coupling,
            "children": mapped_children,
        }

    def set_evaluator_outcome(self, node_key: str, outcome: Dict[str, Any]) -> None:
        normalized = self._normalize_node_key(node_key)
        self.evaluator_script.setdefault("outcomes", {})[normalized] = self._normalize_outcome(outcome)

    def set_evaluator_outcomes(self, table: List[Dict[str, str]]) -> None:
        outcomes: Dict[str, Dict[str, Any]] = {}
        for row in table:
            node_key = row.get("node_key") or row.get("node")
            if not node_key:
                continue
            outcomes[self._normalize_node_key(str(node_key))] = self._normalize_outcome(dict(row))
        self.evaluator_script["outcomes"] = outcomes

    def set_rubric(self, rubric: Dict[str, int]) -> None:
        self.rubric = rubric

    def _normalize_outcome(self, outcome: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(outcome)
        if "evidence_ids" not in normalized and "evidence_refs" in normalized:
            ref = str(normalized.get("evidence_refs") or "").strip()
            normalized["evidence_ids"] = [] if ref in {"", "(empty)"} else [ref]
        if "evidence_ids" in normalized and isinstance(normalized.get("evidence_ids"), str):
            refs = str(normalized.get("evidence_ids") or "").strip()
            if refs in {"", "(empty)"}:
                normalized["evidence_ids"] = []
            else:
                normalized["evidence_ids"] = [item.strip() for item in refs.split(",") if item.strip()]
        if "evidence_ids" not in normalized:
            normalized["evidence_ids"] = []
        if "evidence_quality" not in normalized:
            normalized["evidence_quality"] = "direct" if normalized["evidence_ids"] else "none"
        normalized.setdefault("reasoning_summary", "BDD evaluator stub.")
        normalized.setdefault("defeaters", ["None noted."])
        normalized.setdefault("uncertainty_source", "BDD evaluator stub.")
        normalized.setdefault("assumptions", [])
        return normalized

    def set_ledger(self, table: List[Dict[str, str]]) -> None:
        self.ledger = {row["id"]: float(row["p_ledger"]) for row in table}

    def set_epsilon(self, epsilon: float) -> None:
        self.epsilon_override = epsilon

    def set_scoped_root(self, root_id: str) -> None:
        self.decomposer_script.setdefault("scoped_roots", set()).add(root_id)

    def set_slot_initial_p(self, node_key: str, p_value: float) -> None:
        self.decomposer_script.setdefault("slot_initial_p", {})[node_key] = p_value

    def set_child_evaluated(self, child_id: str, p_value: float, evidence_ids: List[str]) -> None:
        canonical = self._resolve_child_alias(child_id)
        self.evaluator_script.setdefault("child_evaluations", {})[canonical] = {
            "p": p_value,
            "A": 1,
            "B": 1,
            "C": 1,
            "D": 1,
            "evidence_ids": evidence_ids,
            "evidence_quality": "direct" if evidence_ids else "none",
            "reasoning_summary": "Supported by listed evidence.",
            "defeaters": ["None noted."],
            "uncertainty_source": "BDD test stub.",
            "assumptions": [],
        }

    def _normalize_node_key(self, node_key: str) -> str:
        normalized = str(node_key).strip()
        parts = normalized.split(":")
        if len(parts) < 3:
            return normalized
        slot_key = ":".join(parts[:2])
        alias = parts[2]
        mapped = self.child_id_map.get(slot_key, {}).get(alias)
        if mapped:
            return f"{slot_key}:{mapped}"
        return normalized

    def _resolve_child_alias(self, child_id: str) -> str:
        alias = str(child_id).strip()
        matches = {mapping.get(alias) for mapping in self.child_id_map.values() if alias in mapping}
        matches.discard(None)
        if len(matches) == 1:
            return next(iter(matches))
        return alias

    def run_engine(self, mode: str) -> None:
        run_mode: Optional[str] = None
        run_count: Optional[int] = None
        run_target: Optional[str] = None
        if mode.startswith("start_session:"):
            scope = mode.split(":", 1)[1]
            roots = self.roots
            run_mode = "start_only"
        elif mode == "until_credits_exhausted":
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots
            run_mode = "until_credits_exhausted"
        elif mode == "until_stops":
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots
            run_mode = "until_stops"
        elif mode == "run_set_a":
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots_a
            run_mode = "until_stops"
        elif mode == "run_set_b":
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots_b
            run_mode = "until_stops"
        elif mode.startswith("operations:"):
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots
            run_mode = "operations"
            run_count = int(mode.split(":", 1)[1])
        elif mode.startswith("evaluations_children:"):
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots
            run_mode = "evaluations_children"
            run_count = int(mode.split(":", 1)[1])
        elif mode.startswith("evaluation:"):
            scope = self.config.get("scope", "Untitled scope")
            roots = self.roots
            run_mode = "evaluation"
            parts = mode.split(":")
            if len(parts) == 2:
                run_count = int(parts[1])
            else:
                run_target = ":".join(parts[1:-1])
                run_count = int(parts[-1])
        else:
            self.mark_pending(f"Engine execution not implemented for mode: {mode}")
            return

        if roots:
            for root in roots:
                self._ensure_required_slots(root.get("id"))

        session_request = self._build_request(
            scope,
            roots,
            run_mode=run_mode,
            run_count=run_count,
            run_target=run_target,
        )
        deps = self._build_deps()
        self.initial_ledger = session_request.initial_ledger or {}
        if not self.initial_ledger:
            count_named = len(roots)
            gamma = float(self.config.get("gamma", 0.0))
            base_p = (1.0 - gamma) / count_named if count_named else 0.0
            self.initial_ledger = {row["id"]: base_p for row in roots}
            self.initial_ledger["H_other"] = gamma if count_named else 1.0
        result = run_session(session_request, deps)
        result_view = result.to_dict_view()
        if mode == "run_set_b":
            self.replay_result = result_view
        else:
            self.result = result_view
            if mode.startswith("start_session:") and not self.replay_result:
                reversed_roots = list(reversed(roots))
                replay_request = self._build_request(
                    scope,
                    reversed_roots,
                    run_mode=run_mode,
                    run_count=run_count,
                    run_target=run_target,
                )
                replay_deps = self._build_deps()
                replay_result = run_session(replay_request, replay_deps)
                self.replay_result = replay_result.to_dict_view()

    def derive_k_from_rubric(self) -> None:
        from abductio_core.application.use_cases.run_session import _derive_k_from_rubric

        base_k, guardrail = _derive_k_from_rubric(self.rubric)
        self.guardrail_applied = guardrail
        self.derived_k = base_k

    def _build_request(
        self,
        scope: str,
        roots: List[Dict[str, Any]],
        *,
        run_mode: Optional[str] = None,
        run_count: Optional[int] = None,
        run_target: Optional[str] = None,
    ) -> SessionRequest:
        config = SessionConfig(
            tau=float(self.config.get("tau", 0.0)),
            epsilon=float(self.epsilon_override if self.epsilon_override is not None else self.config.get("epsilon", 0.0)),
            gamma=float(self.config.get("gamma", 0.0)),
            alpha=float(self.config.get("alpha", 0.0)),
            beta=float(self.config.get("beta", 1.0)),
            W=float(self.config.get("W", 3.0)),
            lambda_voi=float(self.config.get("lambda_voi", 0.1)),
            world_mode=str(self.config.get("world_mode", "open")),
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
        evidence_ids: List[str] = []
        for outcome in self.evaluator_script.get("outcomes", {}).values():
            if isinstance(outcome, dict):
                ids = outcome.get("evidence_ids")
                if isinstance(ids, list):
                    evidence_ids.extend([str(item) for item in ids if isinstance(item, str)])
        for outcome in self.evaluator_script.get("child_evaluations", {}).values():
            if isinstance(outcome, dict):
                ids = outcome.get("evidence_ids")
                if isinstance(ids, list):
                    evidence_ids.extend([str(item) for item in ids if isinstance(item, str)])
        return SessionRequest(
            scope=scope,
            roots=root_specs,
            config=config,
            credits=credits,
            required_slots=self.required_slots,
            run_mode=run_mode,
            run_count=run_count,
            run_target=run_target,
            initial_ledger=self.ledger or None,
            evidence_items=[
                {"id": evidence_id, "source": "bdd", "text": f"Evidence {evidence_id}."}
                for evidence_id in sorted(set(evidence_ids))
            ],
            pre_scoped_roots=sorted(self.decomposer_script.get("scoped_roots", [])),
            slot_k_min=self.decomposer_script.get("slot_k_min"),
            slot_initial_p=self.decomposer_script.get("slot_initial_p"),
            force_scope_fail_root=self.decomposer_script.get("force_scope_fail_root"),
        )

    def _ensure_required_slots(self, root_id: Optional[str]) -> None:
        if not root_id:
            return
        if not self.required_slots:
            return
        fail_roots = self.decomposer_script.get("fail_roots", set())
        if root_id in fail_roots:
            return
        scope = self.decomposer_script.setdefault("scope_roots", [])
        if scope == "all":
            return
        if not isinstance(scope, list):
            scope = []
            self.decomposer_script["scope_roots"] = scope
        if any(row.get("root_id") == root_id for row in scope):
            return
        scope.append({"root_id": root_id})

    def _build_deps(self) -> RunSessionDeps:
        evaluator = DeterministicEvaluator(self.evaluator_script)
        decomposer = DeterministicDecomposer(self.decomposer_script)
        audit_sink = InMemoryAuditSink()
        return RunSessionDeps(
            evaluator=evaluator,
            decomposer=decomposer,
            audit_sink=audit_sink,
        )
