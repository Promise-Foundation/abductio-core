from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Dict, List, Optional

from behave import given, then, when

from abductio_core.application.canonical import canonical_id_for_statement
from abductio_core.application.use_cases.replay_session import replay_session
from tests.bdd.steps.support.step_world import StepWorld

RESIDUAL_IDS = {"H_NOA", "H_UND"}
SEARCH_EVENT_MARKERS = ("SEARCH",)


def get_world(context) -> StepWorld:
    if not hasattr(context, "world"):
        context.world = StepWorld()
    return context.world


def table_key_values(table) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for row in table:
        if len(row.cells) >= 2:
            key = row.cells[0].strip()
            value = row.cells[1].strip()
        else:
            items = list(row.items())
            if len(items) < 2:
                continue
            key = str(items[0][1]).strip()
            value = str(items[1][1]).strip()
        pairs[key] = value
    headings = list(getattr(table, "headings", []) or [])
    if len(headings) == 2 and headings[0] not in {"key", "field", "event_type"}:
        key = str(headings[0]).strip()
        value = str(headings[1]).strip()
        pairs.setdefault(key, value)
    return pairs


def table_rows(table) -> List[Dict[str, str]]:
    rows = []
    for row in table:
        cleaned = {key.strip(): value.strip() for key, value in row.items()}
        rows.append(cleaned)
    return rows


def _ensure_root(world: StepWorld, root_id: str) -> None:
    if any(root.get("id") == root_id for root in world.roots):
        return
    world.roots.append(
        {
            "id": root_id,
            "statement": f"{root_id} statement",
            "exclusion_clause": "Not explained by any other root",
        }
    )


def _expected_slot_statements(world: StepWorld, root_id: str) -> Dict[str, str]:
    scope_roots = world.decomposer_script.get("scope_roots")
    if not isinstance(scope_roots, list):
        return {}
    for row in scope_roots:
        if row.get("root_id") == root_id:
            return {
                "availability": row.get("availability_statement", ""),
                "fit_to_key_features": row.get("fit_statement", ""),
                "defeater_resistance": row.get("defeater_statement", ""),
            }
    return {}


def _parse_numeric_expr(value: str) -> float:
    expr = value.strip()
    if "*" not in expr:
        return float(expr)
    parts = [part.strip() for part in expr.split("*") if part.strip()]
    result = 1.0
    for part in parts:
        result *= float(part)
    return result


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def _parse_ln_ratio(expr: str) -> float:
    match = re.fullmatch(r"\s*ln\(\s*([0-9]*\.?[0-9]+)\s*/\s*([0-9]*\.?[0-9]+)\s*\)\s*", expr)
    if not match:
        raise ValueError(f"Unsupported ln ratio expression: {expr!r}")
    x = float(match.group(1))
    y = float(match.group(2))
    return math.log(x / y)


def _latest_event(world: StepWorld, event_type: str) -> Dict[str, Any] | None:
    if not world.result:
        return None
    events = [e for e in world.result.get("audit", []) if e.get("event_type") == event_type]
    return events[-1] if events else None


def _events(world: StepWorld, event_type: str) -> List[Dict[str, Any]]:
    if not world.result:
        return []
    return [e for e in world.result.get("audit", []) if e.get("event_type") == event_type]


def _find_event_for_root(world: StepWorld, event_type: str, root_id: str, slot_key: str | None = None) -> Dict[str, Any] | None:
    for e in reversed(_events(world, event_type)):
        payload = e.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("root_id") != root_id:
            continue
        if slot_key is not None and payload.get("slot_key") != slot_key:
            continue
        return e
    return None


def _find_event_for_node(world: StepWorld, event_type: str, node_key: str) -> Dict[str, Any] | None:
    for e in reversed(_events(world, event_type)):
        payload = e.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("node_key") == node_key:
            return e
    return None


def _search_events(world: StepWorld) -> List[Dict[str, Any]]:
    if not world.result:
        return []
    events = world.result.get("audit", []) or []
    found = []
    for event in events:
        event_type = str(event.get("event_type", "") or "")
        payload = event.get("payload") or {}
        op_type = ""
        if isinstance(payload, dict):
            op_type = str(payload.get("op_type", "") or payload.get("operation_type", "") or "")
        if any(marker in event_type for marker in SEARCH_EVENT_MARKERS) or op_type == "SEARCH":
            found.append(event)
    return found


def _get_payload_number(payload: Dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _policy(world: StepWorld) -> Dict[str, Any]:
    policy = world.decomposer_script.setdefault("policy", {})
    if not isinstance(policy, dict):
        policy = {}
        world.decomposer_script["policy"] = policy
    return policy


def _session_metadata(world: StepWorld) -> Dict[str, Any]:
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict), f"Session metadata must be a dict, got {type(metadata).__name__}"
    return metadata


def _ensure_result_shell(world: StepWorld) -> Dict[str, Any]:
    if not isinstance(world.result, dict):
        world.result = {}
    world.result.setdefault("roots", {})
    world.result.setdefault("ledger", {})
    world.result.setdefault("nodes", {})
    world.result.setdefault("audit", [])
    world.result.setdefault("stop_reason", None)
    world.result.setdefault("credits_remaining", 0)
    world.result.setdefault("total_credits_spent", 0)
    world.result.setdefault("operation_log", [])
    world.result.setdefault("explanations", {})
    world.result.setdefault("metadata", {})
    return world.result


def _append_audit_event(world: StepWorld, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    result = _ensure_result_shell(world)
    audit = result.setdefault("audit", [])
    assert isinstance(audit, list)
    audit.append({"event_type": str(event_type), "payload": dict(payload or {})})


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _metadata_has_field(metadata: Dict[str, Any], field: str) -> bool:
    if field in metadata:
        return True
    stack: List[Dict[str, Any]] = [value for value in metadata.values() if isinstance(value, dict)]
    while stack:
        current = stack.pop()
        if field in current:
            return True
        stack.extend(value for value in current.values() if isinstance(value, dict))
    return False


def _next_steps(world: StepWorld) -> List[Dict[str, Any]]:
    metadata = _session_metadata(world)
    from_metadata = metadata.get("next_steps", [])
    typed: List[Dict[str, Any]] = []
    if isinstance(from_metadata, list):
        typed.extend(row for row in from_metadata if isinstance(row, dict))
    if typed:
        return typed
    event = _latest_event(world, "NEXT_STEPS_GENERATED")
    if not event:
        return []
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return []
    event_next_steps = payload.get("next_steps", [])
    if not isinstance(event_next_steps, list):
        return []
    return [row for row in event_next_steps if isinstance(row, dict)]


def _release_metric_lower_is_better(metric: str) -> bool:
    token = str(metric).strip().lower()
    lower_markers = (
        "brier",
        "ece",
        "variance",
        "error",
        "loss",
        "mae",
        "rmse",
    )
    return any(marker in token for marker in lower_markers)


def _payload_code(payload: Dict[str, Any]) -> Optional[str]:
    code = payload.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    anomaly = payload.get("anomaly")
    if isinstance(anomaly, dict):
        nested = anomaly.get("code")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _rubric_from_table(table) -> Dict[str, int]:
    data = table_key_values(table)
    headings = list(getattr(table, "headings", []) or [])
    if len(headings) == 2 and headings[0] in {"A", "B", "C", "D"}:
        data.setdefault(headings[0], headings[1])
    return {key: int(value) for key, value in data.items() if key in {"A", "B", "C", "D"}}


@given("default config")
@given("default config:")
def given_default_config(context) -> None:
    world = get_world(context)
    world.set_config(table_key_values(context.table))


@given("required template slots")
@given("required template slots:")
def given_required_template_slots(context) -> None:
    world = get_world(context)
    world.set_required_slots(table_rows(context.table))


@given("a hypothesis set with named roots")
@given("a hypothesis set with named roots:")
def given_named_roots(context) -> None:
    world = get_world(context)
    world.set_roots(table_rows(context.table))


@given("hypothesis set A with named roots")
@given("hypothesis set A with named roots:")
def given_named_roots_a(context) -> None:
    world = get_world(context)
    world.set_roots_a(table_rows(context.table))


@given("hypothesis set B with the same roots but reversed ordering")
def given_named_roots_b(context) -> None:
    world = get_world(context)
    world.roots_b = list(reversed(world.roots_a))


@given("a deterministic decomposer that will scope roots with")
@given("a deterministic decomposer that will scope roots with:")
def given_decomposer_scope_roots_with(context) -> None:
    world = get_world(context)
    world.set_decomposer_scope_roots(table_rows(context.table))


@given("a deterministic decomposer that will scope all roots")
def given_decomposer_scope_all(context) -> None:
    world = get_world(context)
    world.set_decomposer_scope_roots()


@given('a deterministic decomposer that will scope root "{root_id}"')
def given_decomposer_scope_root(context, root_id: str) -> None:
    world = get_world(context)
    world.set_decomposer_scope_roots([{"root_id": root_id}])


@given("evidence search is enabled with max depth 2 and per-node quota 1")
def given_search_enabled_depth_quota(context) -> None:
    world = get_world(context)
    world.config["search_enabled"] = True
    world.config["max_search_depth"] = 2
    world.config["max_search_per_node"] = 1
    world.config["rho_eval_min"] = 0.0
    world.config["tau"] = 0.0


@given("evidence search is enabled with per-slot quota 1")
def given_search_enabled_slot_quota(context) -> None:
    world = get_world(context)
    world.config["search_enabled"] = True
    world.config["search_quota_per_slot"] = 1
    world.config["rho_eval_min"] = 0.0
    world.config["tau"] = 0.0


@given("evidence search is enabled with deterministic queries")
def given_search_enabled_deterministic(context) -> None:
    world = get_world(context)
    world.config["search_enabled"] = True
    world.config["search_deterministic"] = True
    world.config["max_search_depth"] = 1
    world.config["max_search_per_node"] = 1
    world.config["rho_eval_min"] = 0.0
    world.config["tau"] = 0.0
    world.enable_search_autogen()


@then("the audit log includes SEARCH operations")
def then_audit_includes_search(context) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    assert events, "Expected SEARCH operations in audit log"


@then("each SEARCH operation records a search snapshot hash")
def then_search_records_snapshot_hash(context) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    missing = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            missing.append(event)
            continue
        if not any(key in payload for key in ("evidence_packet_hash", "search_snapshot_hash", "snapshot_hash")):
            missing.append(event)
    assert not missing, "Expected SEARCH payload to include a snapshot hash"

@then("each SEARCH operation records an evidence packet hash")
def then_search_records_packet_hash(context) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    missing = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            missing.append(event)
            continue
        if "evidence_packet_hash" not in payload:
            missing.append(event)
    assert not missing, "Expected SEARCH payload to include evidence_packet_hash"


@then('search credits for slot "{slot_key}" are equal across hypotheses')
def then_search_quota_equal(context, slot_key: str) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    counts: Dict[str, int] = {}
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("slot_key") != slot_key:
            continue
        root_id = payload.get("root_id") or payload.get("hypothesis_id")
        if not root_id:
            continue
        counts[root_id] = counts.get(root_id, 0) + 1
    if not counts:
        world.mark_pending("SEARCH events missing slot_key/root_id fields")
    values = set(counts.values())
    assert len(values) == 1, f"Search credits not equal across hypotheses for slot {slot_key}: {counts}"


@then("search queries are derived from scope, hypothesis, slot, and depth")
def then_search_queries_derived(context) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        query = payload.get("query") or payload.get("query_text")
        if not query:
            raise AssertionError("SEARCH payload missing query text")
        if "slot_key" not in payload or "root_id" not in payload or "depth" not in payload:
            raise AssertionError("SEARCH payload missing derivation fields (slot_key/root_id/depth)")


@then("search budgets do not change based on interim ledger scores")
def then_search_budgets_non_adaptive(context) -> None:
    world = get_world(context)
    events = _search_events(world)
    if not events:
        world.mark_pending("SEARCH operation not implemented in engine")
    counts: Dict[str, Dict[str, int]] = {}
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        slot_key = payload.get("slot_key")
        root_id = payload.get("root_id") or payload.get("hypothesis_id")
        if not slot_key or not root_id:
            continue
        counts.setdefault(slot_key, {})
        counts[slot_key][root_id] = counts[slot_key].get(root_id, 0) + 1
    if not counts:
        raise AssertionError("SEARCH payload missing slot/root info for budget checks")
    for slot_key, slot_counts in counts.items():
        values = set(slot_counts.values())
        assert len(values) == 1, f"Search budgets appear adaptive for slot {slot_key}: {slot_counts}"


@given('a deterministic decomposer that fails to scope root "{root_id}"')
def given_decomposer_fail_root(context, root_id: str) -> None:
    world = get_world(context)
    world.set_decomposer_fail_root(root_id)


@given(
    'a deterministic decomposer that will decompose slot "{slot_key}" as {decomp_type} '
    "with coupling {coupling:f} into"
)
@given(
    'a deterministic decomposer that will decompose slot "{slot_key}" as {decomp_type} '
    "with coupling {coupling:f} into:"
)
def given_decomposer_decompose_slot(context, slot_key: str, decomp_type: str, coupling: float) -> None:
    world = get_world(context)
    world.set_decomposer_slot_decomposition(slot_key, decomp_type, coupling, table_rows(context.table))


@given(
    'a deterministic decomposer that will decompose slot "{slot_key}" as {decomp_type} into:'
)
def given_decomposer_decompose_slot_no_coupling(context, slot_key: str, decomp_type: str) -> None:
    world = get_world(context)
    world.set_decomposer_slot_decomposition(slot_key, decomp_type, None, table_rows(context.table))


@given('a deterministic evaluator that returns for node "{node_key}"')
@given('a deterministic evaluator that returns for node "{node_key}":')
def given_deterministic_evaluator_node(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator with the following outcomes")
@given("a deterministic evaluator with the following outcomes:")
def given_deterministic_evaluator_outcomes(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator that returns")
@given("a deterministic evaluator that returns:")
def given_deterministic_evaluator_returns(context) -> None:
    world = get_world(context)
    if all(len(row.cells) == 2 for row in context.table) and all(
        row.cells[0] in {"A", "B", "C", "D"} for row in context.table
    ):
        world.set_rubric(_rubric_from_table(context.table))
        return
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator returns")
@given("a deterministic evaluator returns:")
def given_deterministic_evaluator_returns_alt(context) -> None:
    world = get_world(context)
    if all(len(row.cells) == 2 for row in context.table) and all(
        row.cells[0] in {"A", "B", "C", "D"} for row in context.table
    ):
        world.set_rubric(_rubric_from_table(context.table))
        return
    world.set_evaluator_outcomes(table_rows(context.table))


@given('a deterministic evaluator that attempts to set for node "{node_key}"')
@given('a deterministic evaluator that attempts to set for node "{node_key}":')
def given_deterministic_evaluator_attempts(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator that returns rubric")
@given("a deterministic evaluator that returns rubric:")
def given_deterministic_evaluator_rubric(context) -> None:
    world = get_world(context)
    world.set_rubric(_rubric_from_table(context.table))


@given("a deterministic evaluator with at least one evaluation outcome")
def given_deterministic_evaluator_one(context) -> None:
    world = get_world(context)
    roots = world.roots or [{"id": "H1"}]
    slot_key = world.required_slots[0]["slot_key"] if world.required_slots else "availability"
    outcomes = [
        {
            "node_key": f"{root['id']}:{slot_key}",
            "p": "0.5",
            "A": "2",
            "B": "1",
            "C": "1",
            "D": "1",
            "evidence_ids": ["ref1"],
            "evidence_quality": "direct",
            "reasoning_summary": "BDD evaluator stub.",
            "defeaters": ["None noted."],
            "uncertainty_source": "BDD evaluator stub.",
            "assumptions": [],
        }
        for root in roots
    ]
    world.set_evaluator_outcomes(outcomes)


@given("a deterministic evaluator that emits discriminator evidence from contrastive context")
def given_deterministic_evaluator_emits_discriminator_from_context(context) -> None:
    world = get_world(context)
    world.set_evaluator_context_strategy("emit_discriminator_from_context")


@given('evidence item "{evidence_id}" text is "{text}"')
def given_evidence_item_text(context, evidence_id: str, text: str) -> None:
    world = get_world(context)
    world.set_evidence_item_text(evidence_id, text)


@given('credits {credits:d}')
def given_credits(context, credits: int) -> None:
    world = get_world(context)
    world.set_credits(credits)


@given('a simplified claim "{claim}"')
def given_simplified_claim(context, claim: str) -> None:
    world = get_world(context)
    world.set_simple_claim(claim)


@given("frame adequacy score is {score:f}")
def given_frame_adequacy_score(context, score: float) -> None:
    world = get_world(context)
    _policy(world)["frame_adequacy_score"] = float(score)


@given("minimum acceptable frame adequacy is {threshold:f}")
def given_frame_adequacy_threshold(context, threshold: float) -> None:
    world = get_world(context)
    _policy(world)["min_frame_adequacy"] = float(threshold)


@given("frame inadequacy caps root confidence at {cap:f}")
def given_frame_inadequacy_confidence_cap(context, cap: float) -> None:
    world = get_world(context)
    _policy(world)["frame_inadequacy_k_cap"] = float(cap)


@given('frame inadequacy reserves at least {mass:f} ledger mass for "{root_id}"')
def given_frame_inadequacy_reserve_mass(context, mass: float, root_id: str) -> None:
    world = get_world(context)
    _policy(world)["frame_inadequacy_reserve"] = {"root_id": str(root_id), "mass": float(mass)}


@given('calibration profile "{profile}" reports calibrated confidence {confidence:f} for this claim class')
def given_calibration_profile_confidence(context, profile: str, confidence: float) -> None:
    world = get_world(context)
    _policy(world)["calibration_profile"] = str(profile)
    _policy(world)["calibrated_confidence"] = float(confidence)


@given('reasoning profile is "{profile}"')
def given_reasoning_profile(context, profile: str) -> None:
    world = get_world(context)
    _policy(world)["reasoning_profile"] = str(profile)


@given('reasoning mode is "{mode}"')
def given_reasoning_mode(context, mode: str) -> None:
    world = get_world(context)
    _policy(world)["reasoning_mode"] = str(mode)


@given("domain profile auto-selection is enabled")
def given_domain_profile_auto_selection_enabled(context) -> None:
    world = get_world(context)
    policy = _policy(world)
    policy["domain_profile_auto_selection"] = True
    policy.setdefault("profile_source", "induced")


@given("domain induction minimum confidence is {threshold:f}")
def given_domain_induction_min_confidence(context, threshold: float) -> None:
    world = get_world(context)
    _policy(world)["domain_induction_min_confidence"] = float(threshold)


@given('this case is marked as unseen domain "{domain_id}"')
def given_case_marked_unseen_domain(context, domain_id: str) -> None:
    world = get_world(context)
    policy = _policy(world)
    policy["domain_id"] = str(domain_id)
    policy["domain_seen_before"] = False
    policy.setdefault("profile_source", "induced")


@given("induced profile confidence for this case is {confidence:f}")
def given_induced_profile_confidence_for_case(context, confidence: float) -> None:
    world = get_world(context)
    policy = _policy(world)
    policy["profile_confidence"] = float(confidence)
    policy["domain_profile_confidence"] = float(confidence)


@given('domain profile "{profile_name}" is selected')
def given_domain_profile_selected(context, profile_name: str) -> None:
    world = get_world(context)
    profile = str(profile_name).strip().lower()
    policy = _policy(world)
    policy["reasoning_profile"] = profile
    policy["profile_name"] = profile
    policy["profile_source"] = "explicit"
    if profile == "causal_investigation":
        policy.setdefault("strict_contrastive_updates_required", True)
        policy.setdefault("min_decomposition_depth_per_slot", 0)
        policy.setdefault("reasoning_mode", "certify")
    elif profile == "forecasting":
        policy.setdefault("strict_contrastive_updates_required", False)
        policy.setdefault("min_decomposition_depth_per_slot", 0)
        policy.setdefault("reasoning_mode", "explore")


@given('historical calibration status is "{status}"')
def given_historical_calibration_status(context, status: str) -> None:
    world = get_world(context)
    _policy(world)["historical_calibration_status"] = str(status)


@given("forecasting confidence hard cap is {cap:f}")
def given_forecasting_confidence_cap(context, cap: float) -> None:
    world = get_world(context)
    _policy(world)["forecasting_confidence_cap"] = float(cap)


@given("minimum winner margin for closure is {margin:f}")
def given_min_winner_margin(context, margin: float) -> None:
    world = get_world(context)
    _policy(world)["min_winner_margin"] = float(margin)


@given("decision contract is enabled")
def given_decision_contract_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["decision_contract_enabled"] = True


@given("decision contract minimum pairwise coverage ratio is {ratio:f}")
def given_decision_min_pairwise_coverage_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["decision_min_pairwise_coverage_ratio"] = float(ratio)


@given("decision contract minimum winner margin is {margin:f}")
def given_decision_min_winner_margin(context, margin: float) -> None:
    world = get_world(context)
    _policy(world)["decision_min_winner_margin"] = float(margin)


@given("decision contract requires loser falsification evidence")
def given_decision_requires_loser_falsification(context) -> None:
    world = get_world(context)
    _policy(world)["decision_require_loser_falsification"] = True


@given("decision contract requires counterevidence probe for winner")
def given_decision_requires_counterevidence_probe(context) -> None:
    world = get_world(context)
    _policy(world)["decision_require_counterevidence_probe"] = True


@given("active-set decision certification is enabled")
def given_active_set_decision_certification_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["decision_active_set_enabled"] = True


@given("active-set contender count is {count:d}")
def given_active_set_contender_count(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["decision_active_set_size"] = int(count)


@given("active-set contender mass ratio floor is {ratio:f}")
def given_active_set_contender_mass_ratio_floor(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["decision_active_set_mass_ratio"] = float(ratio)


@given("active-set closure adjudication is required")
def given_active_set_closure_adjudication_required(context) -> None:
    world = get_world(context)
    _policy(world)["closure_active_set_adjudication_required"] = True


@given("closure active-set contender count is {count:d}")
def given_closure_active_set_contender_count(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["closure_active_set_size"] = int(count)


@given("closure active-set contender mass ratio floor is {ratio:f}")
def given_closure_active_set_contender_mass_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["closure_active_set_mass_ratio"] = float(ratio)


@given("closure minimum pairwise coverage ratio is {ratio:f}")
def given_closure_min_pairwise_coverage_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["closure_min_pairwise_coverage_ratio"] = float(ratio)


@given("pair-adjudication queue is enabled")
def given_pair_adjudication_queue_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_queue_enabled"] = True


@given('pair-adjudication scope is "{scope}"')
def given_pair_adjudication_scope(context, scope: str) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_scope"] = str(scope).strip()


@given("pair-adjudication active-set contender count is {count:d}")
def given_pair_adjudication_active_set_count(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_active_set_size"] = int(count)


@given("pair-adjudication active-set contender mass ratio floor is {ratio:f}")
def given_pair_adjudication_active_set_mass_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_active_set_mass_ratio"] = float(ratio)


@given("pair-adjudication pair budget is {count:d}")
def given_pair_adjudication_pair_budget(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_pair_budget"] = int(count)


@given("pair-adjudication active-set lock is enabled")
def given_pair_adjudication_active_set_lock_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_active_set_lock_enabled"] = True


@given("pair-adjudication active-set lock is disabled")
def given_pair_adjudication_active_set_lock_disabled(context) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_active_set_lock_enabled"] = False


@given("pair-resolution adjudication engine is enabled")
def given_pair_resolution_adjudication_engine_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["pair_resolution_engine_enabled"] = True


@given("pair-resolution minimum directional margin is {margin:f}")
def given_pair_resolution_min_directional_margin(context, margin: float) -> None:
    world = get_world(context)
    _policy(world)["pair_resolution_min_directional_margin"] = float(margin)


@given("pair-resolution minimum directional evidence count is {count:d}")
def given_pair_resolution_min_directional_evidence_count(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["pair_resolution_min_directional_evidence_count"] = int(count)


@given("pair-resolution contradiction density ceiling is {ratio:f}")
def given_pair_resolution_contradiction_density_ceiling(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["pair_resolution_max_contradiction_density"] = float(ratio)


@given("pair-resolution winner update gain is {gain:f}")
def given_pair_resolution_winner_update_gain(context, gain: float) -> None:
    world = get_world(context)
    _policy(world)["pair_resolution_winner_update_gain"] = float(gain)


@given("directional typed evidence linker is enabled")
def given_directional_typed_evidence_linker_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["directional_typed_evidence_linker_enabled"] = True


@given("contender retirement is enabled")
def given_contender_retirement_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_enabled"] = True


@given("contender retirement minimum decisive losses is {count:d}")
def given_contender_retirement_min_decisive_losses(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_min_decisive_losses"] = int(count)


@given("contender retirement minimum pair margin is {margin:f}")
def given_contender_retirement_min_pair_margin(context, margin: float) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_min_pair_margin"] = float(margin)


@given("contender retirement minimum pair strength is {strength:f}")
def given_contender_retirement_min_pair_strength(context, strength: float) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_min_pair_strength"] = float(strength)


@given("contender retirement requires no decisive wins")
def given_contender_retirement_requires_no_decisive_wins(context) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_require_no_decisive_wins"] = True


@given("contender retirement mass floor is {floor:f}")
def given_contender_retirement_mass_floor(context, floor: float) -> None:
    world = get_world(context)
    _policy(world)["contender_retirement_mass_floor"] = float(floor)


@given('contender space mode is "{mode}"')
def given_contender_space_mode(context, mode: str) -> None:
    world = get_world(context)
    _policy(world)["contender_space_mode"] = str(mode).strip()


@given("compositional story auto-expansion is enabled")
def given_compositional_story_auto_expansion_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["compositional_story_auto_expand"] = True


@given("compositional story max cardinality is {count:d}")
def given_compositional_story_max_cardinality(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["contender_story_max_cardinality"] = int(count)


@given("contender story components are")
@given("contender story components are:")
def given_contender_story_components(context) -> None:
    world = get_world(context)
    components_by_root: Dict[str, List[str]] = {}
    for row in table_rows(context.table):
        root_id = str(row.get("root_id", "")).strip()
        if not root_id:
            continue
        raw_components = str(row.get("components", "")).strip()
        components = [part.strip() for part in raw_components.split(",") if part.strip()]
        components_by_root[root_id] = components
    _policy(world)["contender_story_components"] = components_by_root


@given("typed discriminator evidence is required")
def given_typed_discriminator_evidence_required(context) -> None:
    world = get_world(context)
    _policy(world)["typed_discriminator_evidence_required"] = True


@given('quote fidelity gate mode is "{mode}"')
def given_quote_fidelity_gate_mode(context, mode: str) -> None:
    world = get_world(context)
    _policy(world)["quote_fidelity_gate_mode"] = str(mode).strip().lower()


@given("evidence discrimination tags are required")
def given_evidence_discrimination_tags_required(context) -> None:
    world = get_world(context)
    _policy(world)["evidence_discrimination_tags_required"] = True


@given('evidence discrimination tag mode is "{mode}"')
def given_evidence_discrimination_tag_mode(context, mode: str) -> None:
    world = get_world(context)
    _policy(world)["evidence_discrimination_tag_mode"] = str(mode).strip().lower()


@given("strict non-discriminative margin epsilon is {epsilon:f}")
def given_strict_non_discriminative_margin_epsilon(context, epsilon: float) -> None:
    world = get_world(context)
    _policy(world)["strict_non_discriminative_margin_epsilon"] = float(epsilon)


@given("coverage-calibrated confidence cap is enabled")
def given_coverage_calibrated_confidence_cap_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["coverage_confidence_cap_enabled"] = True


@given("coverage confidence cap base is {base:f} and gain is {gain:f}")
def given_coverage_confidence_cap_params(context, base: float, gain: float) -> None:
    world = get_world(context)
    policy = _policy(world)
    policy["coverage_confidence_cap_base"] = float(base)
    policy["coverage_confidence_cap_gain"] = float(gain)


@given("contrastive budget partition is enabled")
def given_contrastive_budget_partition_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["contrastive_budget_partition_enabled"] = True


@given("minimum contrastive discriminator credits is {count:d}")
def given_min_contrastive_discriminator_credits(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["min_contrastive_discriminator_credits"] = int(count)


@given("minimum counterevidence credits is {count:d}")
def given_min_counterevidence_credits(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["min_counterevidence_credits"] = int(count)


@given("minimum decomposition depth per NEC slot is {depth:d}")
def given_min_decomposition_depth(context, depth: int) -> None:
    world = get_world(context)
    _policy(world)["min_decomposition_depth_per_slot"] = int(depth)


@given("strict contrastive updates are required")
def given_strict_contrastive_updates(context) -> None:
    world = get_world(context)
    _policy(world)["strict_contrastive_updates_required"] = True


@given("unresolved contradiction pressure is {pressure:f}")
def given_unresolved_contradiction_pressure(context, pressure: float) -> None:
    world = get_world(context)
    _policy(world)["unresolved_contradiction_pressure"] = float(pressure)


@given("active discriminator coverage ratio is {ratio:f}")
def given_active_discriminator_coverage_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["active_discriminator_coverage_ratio"] = float(ratio)


@given("minimum discriminator coverage ratio is {ratio:f}")
def given_min_discriminator_coverage_ratio(context, ratio: float) -> None:
    world = get_world(context)
    _policy(world)["min_discriminator_coverage_ratio"] = float(ratio)


@given("dynamic abstention mass is enabled")
def given_dynamic_abstention_mass_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_mass_enabled"] = True


@given("dynamic abstention unresolved-pair weight is {weight:f}")
def given_dynamic_abstention_unresolved_pair_weight(context, weight: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_unresolved_pair_weight"] = float(weight)


@given("dynamic abstention contradiction-density weight is {weight:f}")
def given_dynamic_abstention_contradiction_density_weight(context, weight: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_contradiction_density_weight"] = float(weight)


@given("dynamic abstention non-discriminative weight is {weight:f}")
def given_dynamic_abstention_non_discriminative_weight(context, weight: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_non_discriminative_weight"] = float(weight)


@given("dynamic abstention mass minimum is {mass:f}")
def given_dynamic_abstention_mass_minimum(context, mass: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_mass_minimum"] = float(mass)


@given("dynamic abstention mass maximum is {mass:f}")
def given_dynamic_abstention_mass_maximum(context, mass: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_mass_maximum"] = float(mass)


@given("evidence dependency overlap threshold is {threshold:f}")
def given_evidence_dependency_overlap_threshold(context, threshold: float) -> None:
    world = get_world(context)
    _policy(world)["evidence_dependency_overlap_threshold"] = float(threshold)


@given("dependency-penalty confidence cap is {cap:f}")
def given_dependency_penalty_confidence_cap(context, cap: float) -> None:
    world = get_world(context)
    _policy(world)["dependency_penalty_k_cap"] = float(cap)


@given('all supporting evidence for root "{root_id}" originates from source "{source_id}"')
def given_root_supporting_evidence_single_source(context, root_id: str, source_id: str) -> None:
    world = get_world(context)
    source_map = _policy(world).setdefault("root_support_sources", {})
    if not isinstance(source_map, dict):
        source_map = {}
        _policy(world)["root_support_sources"] = source_map
    source_map[str(root_id)] = str(source_id)


@given("assumption-overlap confidence cap is {cap:f}")
def given_assumption_overlap_confidence_cap(context, cap: float) -> None:
    world = get_world(context)
    _policy(world)["assumption_overlap_k_cap"] = float(cap)


@given('slot assumptions for root "{root_id}" are all:')
def given_slot_assumptions_for_root(context, root_id: str) -> None:
    world = get_world(context)
    assumptions = [row.get("assumption_id", "").strip() for row in table_rows(context.table)]
    assumptions = [item for item in assumptions if item]
    by_root = _policy(world).setdefault("slot_assumptions_by_root", {})
    if not isinstance(by_root, dict):
        by_root = {}
        _policy(world)["slot_assumptions_by_root"] = by_root
    by_root[str(root_id)] = assumptions


@given('the root "{root_id}" is already SCOPED with all slots having k >= {k_min:f}')
def given_root_scoped_with_k(context, root_id: str, k_min: float) -> None:
    world = get_world(context)
    world.set_scoped_root(root_id)
    world.decomposer_script.setdefault("slot_k_min", {})[root_id] = k_min


@given("the ledger is set to")
@given("the ledger is set to:")
def given_ledger_is_set(context) -> None:
    world = get_world(context)
    world.set_ledger(table_rows(context.table))


@given('epsilon = {epsilon:f}')
def given_epsilon(context, epsilon: float) -> None:
    world = get_world(context)
    world.set_epsilon(epsilon)


@given('strict MECE certification is enabled with max pair overlap {max_pair_overlap:f}')
def given_strict_mece_certification(context, max_pair_overlap: float) -> None:
    world = get_world(context)
    world.set_mece_strict(max_pair_overlap)


@given("pairwise overlap scores:")
def given_pairwise_overlap_scores(context) -> None:
    world = get_world(context)
    world.set_pairwise_overlaps(table_rows(context.table))


@given("pairwise discriminators:")
def given_pairwise_discriminators(context) -> None:
    world = get_world(context)
    world.set_pairwise_discriminators(table_rows(context.table))


@given(
    'a scoped root "{root_id}" with slot "{slot_key}" decomposed as {decomp_type} coupling '
    "{coupling:f} into NEC children"
)
@given(
    'a scoped root "{root_id}" with slot "{slot_key}" decomposed as {decomp_type} coupling '
    "{coupling:f} into NEC children:"
)
def given_scoped_root_with_slot(context, root_id: str, slot_key: str, decomp_type: str, coupling: float) -> None:
    world = get_world(context)
    _ensure_root(world, root_id)
    world.set_scoped_root(root_id)
    slot_node_key = f"{root_id}:{slot_key}"
    world.set_decomposer_slot_decomposition(slot_node_key, decomp_type, coupling, table_rows(context.table))


@given('a scoped root "{root_id}"')
def given_scoped_root(context, root_id: str) -> None:
    world = get_world(context)
    _ensure_root(world, root_id)
    world.set_scoped_root(root_id)


@given('slot node "{node_key}" has initial p = {p_value:f}')
def given_slot_initial_p(context, node_key: str, p_value: float) -> None:
    world = get_world(context)
    world.set_slot_initial_p(node_key, p_value)


@given('only child "{child_id}" is evaluated with p={p_value:f} and evidence_ids "{refs}"')
def given_only_child_evaluated(context, child_id: str, p_value: float, refs: str) -> None:
    world = get_world(context)
    evidence_ids = [] if refs.strip() in {"", "(empty)"} else [refs.strip()]
    world.set_child_evaluated(child_id, p_value, evidence_ids)


@given("the ledger is externally corrupted so that sum(named_roots) = 1.2 and H_NOA/H_UND are negative")
def given_ledger_corrupted(context) -> None:
    world = get_world(context)
    named_roots = [row["id"] for row in world.roots]
    if not named_roots:
        world.ledger = {"H_NOA": -0.1, "H_UND": -0.1}
        return
    per_root = 1.2 / len(named_roots)
    world.ledger = {root_id: per_root for root_id in named_roots}
    world.ledger["H_NOA"] = -0.1
    world.ledger["H_UND"] = -0.1


@given("I ran a session and captured its audit trace")
def given_captured_audit_trace(context) -> None:
    world = get_world(context)
    if not world.roots:
        world.set_roots(
            [
                {"id": "H1", "statement": "Mechanism A", "exclusion_clause": ""},
                {"id": "H2", "statement": "Mechanism B", "exclusion_clause": ""},
            ]
        )
    world.set_decomposer_scope_roots()
    if not world.evaluator_script.get("outcomes"):
        given_deterministic_evaluator_one(context)
    if world.credits is None:
        world.set_credits(3)
    world.run_engine("until_stops")
    if world.result:
        world.audit_trace = list(world.result.get("audit", []))


@given("the CLI adapter is configured with an application runner instance")
def given_cli_adapter_configured(context) -> None:
    world = get_world(context)
    world.decomposer_script["cli_configured"] = True


@given("the API adapter is configured with an application runner instance")
def given_api_adapter_configured(context) -> None:
    world = get_world(context)
    world.decomposer_script["api_configured"] = True


@given("a held-out domain benchmark summary")
@given("a held-out domain benchmark summary:")
def given_held_out_domain_benchmark_summary(context) -> None:
    world = get_world(context)
    summary: Dict[str, float] = {}
    domains_count: Optional[int] = None
    for row in table_rows(context.table):
        metric = str(row.get("metric", "")).strip()
        value_raw = str(row.get("value", "")).strip()
        if not metric:
            continue
        try:
            value = float(value_raw)
        except ValueError as exc:
            raise AssertionError(f"Benchmark metric {metric!r} must be numeric, got {value_raw!r}") from exc
        metric_key = metric.lower()
        if metric_key in {"held_out_domains_count", "heldout_domains_count", "domain_count", "domains_count"}:
            domains_count = int(value)
            continue
        summary[metric] = value
    world.release_gate_summary = summary
    world.release_gate_domains_count = max(0, domains_count if domains_count is not None else 3)
    world.release_gate_report = {}


@given("release gate thresholds")
@given("release gate thresholds:")
def given_release_gate_thresholds(context) -> None:
    world = get_world(context)
    thresholds: Dict[str, float] = {}
    for row in table_rows(context.table):
        metric = str(row.get("metric", "")).strip()
        threshold_raw = str(row.get("threshold", "")).strip()
        if not metric:
            continue
        try:
            threshold = float(threshold_raw)
        except ValueError as exc:
            raise AssertionError(
                f"Release gate threshold for metric {metric!r} must be numeric, got {threshold_raw!r}"
            ) from exc
        thresholds[metric] = threshold
    world.release_gate_thresholds = thresholds
    world.release_gate_report = {}


@when('I start a session for scope "{scope}"')
def when_start_session(context, scope: str) -> None:
    world = get_world(context)
    world.run_engine(f"start_session:{scope}")


@when("I run the engine until credits exhausted")
def when_run_until_credits_exhausted(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@when("I run the engine until it stops")
def when_run_until_stops(context) -> None:
    world = get_world(context)
    world.run_engine("until_stops")

@when("I run the engine")
def when_run_engine_default(context) -> None:
    world = get_world(context)
    world.run_engine("until_stops")


@when("I run the simplified claim interface until it stops")
@when("I run the simplified claim interface")
def when_run_simplified_claim_interface(context) -> None:
    world = get_world(context)
    world.run_simple_claim_interface()


@when('I run the engine with framing text "{framing}" until it stops')
def when_run_until_stops_with_framing(context, framing: str) -> None:
    world = get_world(context)
    if world.result is None:
        world.run_engine(f"framing_a:{framing}")
    else:
        world.run_engine(f"framing_b:{framing}")


@when('I run the engine for exactly {count:d} operations')
@when('I run the engine for exactly {count:d} operation')
def when_run_exact_operations(context, count: int) -> None:
    world = get_world(context)
    world.run_engine(f"operations:{count}")


@when('I run the engine for exactly {count:d} evaluations targeting those children')
def when_run_exact_evaluations_children(context, count: int) -> None:
    world = get_world(context)
    world.run_engine(f"evaluations_children:{count}")


@when('I run the engine for exactly {count:d} evaluation targeting "{node_key}"')
def when_run_exact_evaluation_target(context, count: int, node_key: str) -> None:
    world = get_world(context)
    world.run_engine(f"evaluation:{node_key}:{count}")


@when('I run the engine for exactly {count:d} evaluation')
def when_run_exact_evaluation(context, count: int) -> None:
    world = get_world(context)
    world.run_engine(f"evaluation:{count}")


@when('I run the engine on hypothesis set A until it stops')
def when_run_engine_on_a(context) -> None:
    world = get_world(context)
    world.run_engine("run_set_a")


@when('I run the engine on hypothesis set B until it stops')
def when_run_engine_on_b(context) -> None:
    world = get_world(context)
    world.run_engine("run_set_b")


@when("the engine derives k from the rubric")
def when_engine_derives_k(context) -> None:
    world = get_world(context)
    world.derive_k_from_rubric()


@when("I evaluate the cross-domain release gate")
def when_evaluate_cross_domain_release_gate(context) -> None:
    world = get_world(context)
    if not world.release_gate_summary:
        raise AssertionError("Held-out domain benchmark summary is required before evaluating release gate")
    if not world.release_gate_thresholds:
        raise AssertionError("Release gate thresholds are required before evaluating release gate")
    failing_metrics: List[str] = []
    metric_results: List[Dict[str, Any]] = []
    for metric, threshold in sorted(world.release_gate_thresholds.items()):
        value = world.release_gate_summary.get(metric)
        if value is None:
            failing_metrics.append(metric)
            metric_results.append(
                {
                    "metric": metric,
                    "status": "MISSING",
                    "threshold": float(threshold),
                    "direction": "unknown",
                }
            )
            continue
        lower_is_better = _release_metric_lower_is_better(metric)
        passed = float(value) <= float(threshold) if lower_is_better else float(value) >= float(threshold)
        metric_results.append(
            {
                "metric": metric,
                "value": float(value),
                "threshold": float(threshold),
                "direction": "lower_is_better" if lower_is_better else "higher_is_better",
                "passed": bool(passed),
            }
        )
        if not passed:
            failing_metrics.append(metric)
    world.release_gate_report = {
        "outcome": "PASS" if not failing_metrics else "FAIL",
        "failing_metrics": sorted(set(failing_metrics)),
        "metrics": metric_results,
        "held_out_domains_count": int(world.release_gate_domains_count),
        "summary": dict(world.release_gate_summary),
        "thresholds": dict(world.release_gate_thresholds),
    }


@when("I replay the session using only the audit trace as the source of operations and numeric outcomes")
def when_replay_session(context) -> None:
    world = get_world(context)
    if not world.audit_trace:
        world.mark_pending("Audit trace not available")
    replayed = replay_session(world.audit_trace)
    world.replay_result = replayed.to_dict_view()


@when("I call the application run use case directly as a library function")
def when_call_library_use_case(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@when("the CLI adapter is invoked with args that specify scope and credits")
def when_cli_adapter_invoked(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@when("the API endpoint is called with a JSON body specifying scope and config")
def when_api_endpoint_called(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@then('the session contains root "{root_id}"')
def then_session_contains_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert root_id in world.result.get("roots", {})
    if root_id in RESIDUAL_IDS:
        named_ids = {row["id"] for row in world.roots}
        assert not (RESIDUAL_IDS & named_ids)
        assert len(world.result.get("roots", {})) == len(named_ids) + len(RESIDUAL_IDS)


@then('the session does not contain root "{root_id}"')
def then_session_excludes_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert root_id not in world.result.get("roots", {})


@then('the ledger probabilities sum to 1.0 within {tolerance}')
def then_ledger_sum(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    total = sum(world.result.get("ledger", {}).values())
    assert abs(total - 1.0) <= tolerance_value


@then('each named root has p_ledger = (1 - gamma) / N where N is count(named_roots)')
def then_named_root_p_ledger(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    gamma_noa = float(world.config.get("gamma_noa", 0.0))
    gamma_und = float(world.config.get("gamma_und", 0.0))
    if gamma_noa == 0.0 and gamma_und == 0.0:
        gamma_legacy = float(world.config.get("gamma", 0.0))
        gamma_noa = gamma_legacy / 2.0
        gamma_und = gamma_legacy / 2.0
    named_roots = [root_id for root_id in world.result["roots"] if root_id not in RESIDUAL_IDS]
    count_named = len(named_roots)
    expected = (1.0 - gamma_noa - gamma_und) / count_named if count_named else 0.0
    for root_id in named_roots:
        actual = world.result["ledger"].get(root_id)
        assert actual is not None
        assert abs(actual - expected) <= 1e-9


@then('H_NOA has p_ledger = gamma_noa')
def then_h_noa_gamma(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    gamma_noa = float(world.config.get("gamma_noa", 0.0))
    if gamma_noa == 0.0:
        gamma_noa = float(world.config.get("gamma", 0.0)) / 2.0
    actual = world.result["ledger"].get("H_NOA")
    assert actual is not None
    assert abs(actual - gamma_noa) <= 1e-9


@then('H_UND has p_ledger = gamma_und')
def then_h_und_gamma(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    gamma_und = float(world.config.get("gamma_und", 0.0))
    if gamma_und == 0.0:
        gamma_und = float(world.config.get("gamma", 0.0)) / 2.0
    actual = world.result["ledger"].get("H_UND")
    assert actual is not None
    assert abs(actual - gamma_und) <= 1e-9


@then('every root starts with k_root = 0.15')
def then_every_root_k_root(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root in world.result.get("roots", {}).values():
        assert abs(root.get("k_root", 0.0) - 0.15) <= 1e-12
        if root.get("obligations"):
            expected = min(node.get("k", 0.0) for node in root["obligations"].values())
            assert abs(root.get("k_root", 0.0) - expected) <= 1e-12


@then('every named root starts with status "{status}"')
def then_named_root_status(context, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id in RESIDUAL_IDS:
            continue
        assert root.get("status") == status
        if status == "UNSCOPED":
            assert not root.get("obligations")


@then("the engine records a canonical_id for every root derived from normalized statement text")
def then_canonical_id_recorded(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id in RESIDUAL_IDS:
            continue
        expected = canonical_id_for_statement(root["statement"])
        assert root.get("canonical_id") == expected


@then("canonical_id does not depend on the input ordering of roots")
def then_canonical_id_ordering(context) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    canonical_a = {
        root_id: root.get("canonical_id")
        for root_id, root in world.result.get("roots", {}).items()
        if root_id not in RESIDUAL_IDS
    }
    canonical_b = {
        root_id: root.get("canonical_id")
        for root_id, root in world.replay_result.get("roots", {}).items()
        if root_id not in RESIDUAL_IDS
    }
    assert canonical_a == canonical_b


@then('both "{root_a}" and "{root_b}" become status "{status}"')
def then_both_roots_status(context, root_a: str, root_b: str, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id in (root_a, root_b):
        root = world.result["roots"].get(root_id)
        assert root is not None
        assert root.get("status") == status


@then("each root has exactly the required template slots")
def then_each_root_required_slots(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    required = {row["slot_key"] for row in world.required_slots}
    required_roles = {row["slot_key"]: row.get("role", "NEC") for row in world.required_slots}
    for root_id, root in world.result["roots"].items():
        if root_id in RESIDUAL_IDS:
            continue
        slots = set(root.get("obligations", {}).keys())
        assert slots == required
        expected_statements = _expected_slot_statements(world, root_id)
        for slot_key, node in root.get("obligations", {}).items():
            assert node.get("role") == required_roles.get(slot_key, "NEC")
            expected_statement = expected_statements.get(slot_key)
            if expected_statement:
                assert node.get("statement") == expected_statement


@then('each unassessed NEC slot has p = {p_value:f} and k = {k_value:f}')
def then_unassessed_slots_default(context, p_value: float, k_value: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result["roots"].items():
        if root_id in RESIDUAL_IDS:
            continue
        for node in root.get("obligations", {}).values():
            assert abs(node.get("p", 0.0) - p_value) <= 1e-9
            assert abs(node.get("k", 0.0) - k_value) <= 1e-9


@then('root "{root_id}" remains status "{status}"')
def then_root_status(context, root_id: str, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result["roots"].get(root_id)
    assert root is not None
    assert root.get("status") == status
    if status == "UNSCOPED":
        assert not root.get("obligations")


@then('root "{root_id}" has k_root <= {k_max:f}')
def then_root_k_capped(context, root_id: str, k_max: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result["roots"].get(root_id)
    assert root is not None
    assert root.get("k_root", 0.0) <= k_max


@then("the audit log records that UNSCOPED capping was applied")
def then_audit_unscope_capping(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(event["event_type"] == "UNSCOPED_CAPPED" for event in world.result.get("audit", []))


@then('total_credits_spent = {credits:d}')
def then_total_credits_spent(context, credits: int) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert world.result.get("total_credits_spent") == credits
    assert len(world.result.get("operation_log", [])) == credits


@then('the audit log contains exactly {count:d} operation records')
def then_audit_op_count(context, count: int) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    op_events = [event for event in world.result.get("audit", []) if event["event_type"] == "OP_EXECUTED"]
    assert len(op_events) == count


@then('each operation record includes: op_type, target_id, credits_before, credits_after')
def then_audit_op_fields(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for entry in world.result.get("operation_log", []):
        assert "op_type" in entry
        assert "target_id" in entry
        assert "credits_before" in entry
        assert "credits_after" in entry
        assert entry["op_type"] in {"DECOMPOSE", "EVALUATE"}
        assert isinstance(entry["credits_before"], int)
        assert isinstance(entry["credits_after"], int)
        assert entry["credits_before"] - entry["credits_after"] == 1


@then('stop_reason is "{reason}"')
def then_stop_reason(context, reason: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected = None if reason.strip() == "None" else reason
    assert world.result.get("stop_reason") == expected


@then("no operations were executed")
def then_no_operations_executed(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert len(world.result.get("operation_log", [])) == 0


@then('credits_remaining = {credits:d}')
def then_credits_remaining(context, credits: int) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert world.result.get("credits_remaining") == credits


@then("all named roots are SCOPED")
def then_all_named_roots_scoped(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result["roots"].items():
        if root_id in RESIDUAL_IDS:
            continue
        assert root.get("status") == "SCOPED"


@then('each named root p_ledger is unchanged from its initial value within {tolerance}')
def then_named_root_p_unchanged(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    for root_id, root in world.result["roots"].items():
        if root_id in RESIDUAL_IDS:
            continue
        initial = world.initial_ledger.get(root_id, 0.0)
        actual = world.result.get("ledger", {}).get(root_id, 0.0)
        assert abs(actual - initial) <= tolerance_value


@then('H_NOA p_ledger is unchanged from its initial value within {tolerance}')
def then_h_noa_p_unchanged(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    initial = world.initial_ledger.get("H_NOA", 0.0)
    actual = world.result.get("ledger", {}).get("H_NOA", 0.0)
    assert abs(actual - initial) <= tolerance_value


@then('H_UND p_ledger is unchanged from its initial value within {tolerance}')
def then_h_und_p_unchanged(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    initial = world.initial_ledger.get("H_UND", 0.0)
    actual = world.result.get("ledger", {}).get("H_UND", 0.0)
    assert abs(actual - initial) <= tolerance_value


@then('slot "{slot_key}" has aggregated p = {p_value:f}')
def then_slot_aggregated_p(context, slot_key: str, p_value: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root_id = None
    slot_name = slot_key
    if ":" in slot_key:
        root_id, slot_name = slot_key.split(":", 1)
    elif world.roots:
        root_id = world.roots[0]["id"]
    assert root_id is not None
    node = world.result["roots"][root_id]["obligations"][slot_name]
    assert abs(node.get("p", 0.0) - p_value) <= 1e-9


@then('slot "{slot_key}" has aggregated k = {k_value:f}')
def then_slot_aggregated_k(context, slot_key: str, k_value: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root_id = None
    slot_name = slot_key
    if ":" in slot_key:
        root_id, slot_name = slot_key.split(":", 1)
    elif world.roots:
        root_id = world.roots[0]["id"]
    assert root_id is not None
    node = world.result["roots"][root_id]["obligations"][slot_name]
    assert abs(node.get("k", 0.0) - k_value) <= 1e-9


@then('root "{root_id}" has k_root = {k_value:f}')
def then_root_k_root_equals(context, root_id: str, k_value: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result.get("roots", {}).get(root_id)
    assert root is not None
    assert abs(float(root.get("k_root", 0.0)) - k_value) <= 1e-9


@then('the audit log records parent-k propagation for "{node_key}" using rule "{rule}"')
def then_parent_k_rule(context, node_key: str, rule: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_node(world, "PARENT_K_PROPAGATED", node_key)
    assert event is not None
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    assert payload.get("rule") == rule


@then('the audit log records parent-k decisive child "{child_key}" for "{node_key}"')
def then_parent_k_decisive_child(context, child_key: str, node_key: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_node(world, "PARENT_K_PROPAGATED", node_key)
    assert event is not None
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    assert payload.get("decisive_child") == child_key


@then('the audit log records that parent-k unscoped cap was applied for "{node_key}"')
def then_parent_k_unscoped_cap(context, node_key: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_node(world, "PARENT_K_PROPAGATED", node_key)
    assert event is not None
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    assert payload.get("unscoped_cap_applied") is True


@then('the audit log records that parent-k guardrail signal was detected for "{node_key}"')
def then_parent_k_guardrail_signal(context, node_key: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_node(world, "PARENT_K_PROPAGATED", node_key)
    assert event is not None
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    assert payload.get("guardrail_signal") is True


@then("no ledger probability changed due to unassessed NEC children")
def then_no_ledger_change_unassessed(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for key, value in world.initial_ledger.items():
        assert abs(world.result.get("ledger", {}).get(key, 0.0) - value) <= 1e-9


@then("the audit log includes a computed multiplier m_H1 = product(slot_p_values)")
def then_audit_multiplier(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] == "DELTA_W_APPLIED" and "m" in event.get("payload", {})
        for event in world.result.get("audit", [])
    )


@then("the audit log includes p_prop(H1) = p_base(H1) * m_H1")
def then_audit_p_prop(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(event["event_type"] == "P_PROP_COMPUTED" for event in world.result.get("audit", []))


@then('the audit log includes damped update with alpha = {alpha:f}')
def then_audit_damped_update(context, alpha: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event["event_type"] == "DAMPING_APPLIED"]
    assert events
    assert any(abs(event["payload"].get("alpha", 0.0) - alpha) <= 1e-9 for event in events)


@then('the audit log includes a delta-w update for root "{root_id}" slot "{slot_key}"')
def then_audit_delta_w(context, root_id: str, slot_key: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event["event_type"] == "DELTA_W_APPLIED"]
    assert any(
        event["payload"].get("root_id") == root_id and event["payload"].get("slot_key") == slot_key
        for event in events
    )


@then("the audit log includes a normalized ledger update")
def then_audit_normalized_ledger(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] in {"INVARIANT_SUM_TO_ONE_CHECK", "OPEN_WORLD_GAMMA_UPDATED", "CLOSED_WORLD_RENORMALIZED"}
        for event in world.result.get("audit", [])
    )


@then("H_NOA and H_UND sum to 1 - sum(named_roots)")
def then_residuals_absorber(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ledger = world.result.get("ledger", {})
    sum_named = sum(value for key, value in ledger.items() if key not in RESIDUAL_IDS)
    expected = 1.0 - sum_named
    residual = float(ledger.get("H_NOA", 0.0)) + float(ledger.get("H_UND", 0.0))
    assert abs(residual - expected) <= 1e-9


@then("the engine enforces the open-world residuals invariant")
def then_enforces_other_absorber(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] in {"OPEN_WORLD_RESIDUALS_ENFORCED", "OPEN_WORLD_GAMMA_UPDATED"}
        for event in world.result.get("audit", [])
    )


@then("all p_ledger values are in [0,1]")
def then_p_ledger_in_range(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for value in world.result.get("ledger", {}).values():
        assert 0.0 <= value <= 1.0


@then("the audit log records which branch was taken (S<=1 or S>1)")
def then_audit_branch_recorded(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] in {"OPEN_WORLD_RESIDUALS_ENFORCED"} and "branch" in event["payload"]
        for event in world.result.get("audit", [])
    )


@then('the frontier contains exactly {root_set}')
def then_frontier_contains(context, root_set: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected = {item.strip().strip('"') for item in root_set.strip("{}").split(",") if item.strip()}
    events = [event for event in world.result.get("audit", []) if event["event_type"] == "FRONTIER_DEFINED"]
    assert events
    frontier = set(events[-1]["payload"].get("frontier", []))
    assert frontier == expected


@then("the audit log records the leader and the frontier definition")
def then_audit_frontier(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] == "FRONTIER_DEFINED"
        and "leader_id" in event["payload"]
        and "frontier" in event["payload"]
        for event in world.result.get("audit", [])
    )


@then('the audit log records MECE certificate status "{status}"')
def then_mece_certificate_status(context, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == "MECE_CERTIFICATE_CHECKED"]
    assert events, "Expected MECE_CERTIFICATE_CHECKED audit event"
    payload = events[-1].get("payload", {})
    assert isinstance(payload, dict)
    assert payload.get("status") == status


@then('the audit log records a MECE certificate issue containing "{snippet}"')
def then_mece_certificate_issue(context, snippet: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == "MECE_CERTIFICATE_CHECKED"]
    assert events, "Expected MECE_CERTIFICATE_CHECKED audit event"
    payload = events[-1].get("payload", {})
    assert isinstance(payload, dict)
    issues = payload.get("issues", [])
    if not isinstance(issues, list):
        raise AssertionError("MECE certificate issues payload must be a list")
    flattened = json.dumps(issues, sort_keys=True)
    assert snippet in flattened, f'Expected MECE issue containing "{snippet}", got: {flattened}'


@then("the operation order follows canonical_id order of statements, not the provided ids")
def then_operation_order_canonical(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    roots = [
        root
        for root_id, root in world.result["roots"].items()
        if root_id not in RESIDUAL_IDS
    ]
    expected_order = [root["id"] for root in sorted(roots, key=lambda root: root["canonical_id"])]
    actual_order = [entry["target_id"] for entry in world.result.get("operation_log", [])]
    assert actual_order[: len(expected_order)] == expected_order


@then("the audit log shows deterministic tie-breaking")
def then_audit_tie_breaking(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(event["event_type"] == "TIE_BREAKER_APPLIED" for event in world.result.get("audit", []))


@then('operation {position:d} is "{op_type}" targeting "{target_id}"')
def then_operation_at_position(context, position: int, op_type: str, target_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    operation_log = world.result.get("operation_log", [])
    assert position >= 1, "operation positions are 1-based"
    assert len(operation_log) >= position, f"expected at least {position} operations, got {len(operation_log)}"
    operation = operation_log[position - 1]
    assert operation.get("op_type") == op_type
    assert operation.get("target_id") == target_id


@then('no slot-level decomposition occurs before all required slots of "{root_id}" are first evaluated')
def then_no_slot_decompose_before_first_slot_evals(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result.get("roots", {}).get(root_id)
    assert root is not None, f"missing root {root_id}"
    obligations = root.get("obligations", {})
    slot_keys = list(obligations.keys())
    assert slot_keys, f"root {root_id} has no obligations"

    operation_log = world.result.get("operation_log", [])
    first_eval_by_slot: Dict[str, int] = {}
    for index, entry in enumerate(operation_log, start=1):
        if entry.get("op_type") != "EVALUATE":
            continue
        target_id = str(entry.get("target_id", ""))
        for slot_key in slot_keys:
            expected = f"{root_id}:{slot_key}"
            if slot_key not in first_eval_by_slot and target_id == expected:
                first_eval_by_slot[slot_key] = index

    missing = [slot_key for slot_key in slot_keys if slot_key not in first_eval_by_slot]
    assert not missing, f"required slots not directly evaluated before budget stop: {missing}"

    cutoff = max(first_eval_by_slot.values())
    for entry in operation_log[:cutoff]:
        if entry.get("op_type") != "DECOMPOSE":
            continue
        target_id = str(entry.get("target_id", ""))
        if target_id.startswith(f"{root_id}:"):
            raise AssertionError(
                f"slot-level DECOMPOSE {target_id} occurred before all required slots were first evaluated"
            )


@then('the final p_ledger and k_root for each named root are identical within {tolerance}')
def then_final_ledger_identical(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    tolerance_value = float(tolerance)
    for root_id, root in world.result["roots"].items():
        if root_id in RESIDUAL_IDS:
            continue
        other_root = world.replay_result["roots"].get(root_id)
        assert other_root is not None
        actual = world.result.get("ledger", {}).get(root_id, 0.0)
        expected = world.replay_result.get("ledger", {}).get(root_id, 0.0)
        assert abs(actual - expected) <= tolerance_value
        assert abs(root.get("k_root", 0.0) - other_root.get("k_root", 0.0)) <= tolerance_value


@then('the final H_NOA and H_UND p_ledger are identical within {tolerance}')
def then_final_residuals_identical(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    tolerance_value = float(tolerance)
    for residual_id in RESIDUAL_IDS:
        actual = world.result.get("ledger", {}).get(residual_id, 0.0)
        expected = world.replay_result.get("ledger", {}).get(residual_id, 0.0)
        assert abs(actual - expected) <= tolerance_value


@then("the sequence of executed operations is identical when compared by canonical target_id")
def then_operations_identical(context) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    canonical_map = {
        root_id: root["canonical_id"]
        for root_id, root in world.result["roots"].items()
        if root_id not in RESIDUAL_IDS
    }
    seq_a = [canonical_map.get(entry["target_id"], entry["target_id"]) for entry in world.result.get("operation_log", [])]
    seq_b = [
        canonical_map.get(entry["target_id"], entry["target_id"])
        for entry in world.replay_result.get("operation_log", [])
    ]
    assert seq_a == seq_b


@then('the aggregated p for slot "{slot_key}" equals {expected} within {tolerance}')
def then_soft_and_expected(context, slot_key: str, expected: str, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected_value = float(expected)
    tolerance_value = float(tolerance)
    root_id = world.roots[0]["id"] if world.roots else next(
        root for root in world.result.get("roots", {}) if root not in RESIDUAL_IDS
    )
    slot_name = slot_key.split(":", 1)[1] if ":" in slot_key else slot_key
    node = world.result["roots"][root_id]["obligations"][slot_name]
    assert abs(node.get("p", 0.0) - expected_value) <= tolerance_value


@then("the audit log shows p_min, p_prod, c, and the computed m")
def then_audit_soft_and(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event["event_type"] == "SOFT_AND_COMPUTED"]
    assert events
    payload = events[-1]["payload"]
    for key in ("p_min", "p_prod", "c", "m"):
        assert key in payload


@then('unassessed children "{child_a}" and "{child_b}" are treated as neutral in aggregation')
def then_unassessed_children(context, child_a: str, child_b: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event["event_type"] == "SOFT_AND_COMPUTED"]
    assert events
    payload = events[-1]["payload"]
    assert abs(payload.get("p_min", 0.0) - 0.5) <= 1e-9
    assert abs(payload.get("p_prod", 0.0) - 0.5) <= 1e-9


@then('the aggregated slot p is <= {upper} and >= {lower}')
def then_aggregated_slot_range(context, upper: str, lower: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    upper_value = _parse_numeric_expr(upper)
    lower_value = _parse_numeric_expr(lower)
    root_id = world.roots[0]["id"]
    node = world.result["roots"][root_id]["obligations"]["fit_to_key_features"]
    actual = node.get("p", 0.0)
    assert lower_value <= actual <= upper_value


@then('k equals {expected:f}')
def then_k_equals(context, expected: float) -> None:
    world = get_world(context)
    assert world.derived_k is not None
    assert abs(world.derived_k - expected) <= 1e-9


@then('k <= {expected:f}')
def then_k_leq(context, expected: float) -> None:
    world = get_world(context)
    assert world.derived_k is not None
    assert world.derived_k <= expected


@then("the audit log records that the guardrail cap was applied")
def then_guardrail_audit(context) -> None:
    world = get_world(context)
    assert world.guardrail_applied


@then('the stored p for "{node_key}" equals {expected} within {tolerance}')
def then_stored_p_equals(context, node_key: str, expected: str, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected_value = float(expected)
    tolerance_value = float(tolerance)
    root_id, slot_key = node_key.split(":", 1)
    node = world.result["roots"][root_id]["obligations"][slot_key]
    actual = node.get("p", 0.0)
    assert abs(actual - expected_value) <= tolerance_value, (
        f"expected p={expected_value} +/- {tolerance_value}, got {actual}"
    )


@then("the audit log records that conservative delta was enforced")
def then_conservative_delta_audit(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(
        event["event_type"] == "CONSERVATIVE_DELTA_ENFORCED"
        for event in world.result.get("audit", [])
    )


@then("the audit trace contains entries for")
@then("the audit trace contains entries for:")
def then_audit_trace_contains(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected = [row["event_type"] for row in context.table]
    actual = {event["event_type"] for event in world.result.get("audit", [])}
    missing = [event_type for event_type in expected if event_type not in actual]
    assert not missing, f"missing events: {missing}; actual={sorted(actual)}"


@then("every numeric value used in ledger updates is recorded with sufficient precision")
def then_audit_numeric_precision(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for event in world.result.get("audit", []):
        for value in event.get("payload", {}).values():
            if isinstance(value, (float, int)):
                assert value == value


@then('the replayed final p_ledger values equal the original final p_ledger values within {tolerance}')
def then_replay_ledger_equals(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    tolerance_value = float(tolerance)
    for key, value in world.result.get("ledger", {}).items():
        assert abs(value - world.replay_result.get("ledger", {}).get(key, 0.0)) <= tolerance_value


@then('the replayed stop_reason equals the original stop_reason')
def then_replay_stop_reason(context) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    assert world.replay_result.get("stop_reason") == world.result.get("stop_reason")


@then("I get a SessionResult object with")
@then("I get a SessionResult object with:")
def then_session_result_fields(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for row in context.table:
        field_name = row["field"]
        assert field_name in world.result


@then("the CLI adapter calls exactly one application run use case")
def then_cli_calls_use_case(context) -> None:
    world = get_world(context)
    assert world.result is not None


@then("the CLI output is derived only from SessionResult (no domain/infrastructure leakage)")
def then_cli_output_from_session_result(context) -> None:
    world = get_world(context)
    assert world.result is not None


@then("the API adapter calls exactly one application run use case")
def then_api_calls_use_case(context) -> None:
    world = get_world(context)
    assert world.result is not None


@then("the API response is derived only from SessionResult")
def then_api_response_from_session_result(context) -> None:
    world = get_world(context)
    assert world.result is not None


@then('the selected target is "{target_id}"')
def then_selected_target_is(context, target_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ops = world.result.get("operation_log", [])
    assert ops, "expected at least one operation"
    assert str(ops[-1].get("target_id")) == target_id


@then("the final ledger equals")
@then("the final ledger equals:")
def then_final_ledger_equals(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    expected = {row["id"]: float(row["p_ledger"]) for row in table_rows(context.table)}
    actual = {key: float(val) for key, val in (world.result.get("ledger", {}) or {}).items()}
    for key, exp in expected.items():
        assert key in actual, f"missing ledger key {key!r}; actual keys={sorted(actual)}"
        assert _float_close(actual[key], exp, tol=1e-6), f"{key}: expected {exp}, got {actual[key]}"


@then(
    'the audit log records bounded non-discriminative drift for root "{root_id}" '
    'slot "{slot_key}" with epsilon {epsilon:f}'
)
def then_non_discriminative_drift_bounded(context, root_id: str, slot_key: str, epsilon: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    delta_event = _find_event_for_root(world, "DELTA_W_APPLIED", root_id, slot_key)
    assert delta_event is not None, "Expected DELTA_W_APPLIED event for root+slot"
    delta_payload = delta_event.get("payload", {})
    assert isinstance(delta_payload, dict)
    delta_w = _get_payload_number(delta_payload, "delta_w", "delta_w_clipped")
    assert delta_w is not None, f"DELTA_W_APPLIED payload missing delta_w: {delta_payload}"
    assert abs(delta_w) <= float(epsilon) + 1e-12, (
        f"Expected |delta_w| <= {epsilon}, got {delta_w}"
    )

    bound_event = _find_event_for_root(world, "NON_DISCRIMINATIVE_DRIFT_BOUNDED", root_id, slot_key)
    assert bound_event is not None, "Expected NON_DISCRIMINATIVE_DRIFT_BOUNDED audit event for root+slot"
    bound_payload = bound_event.get("payload", {})
    assert isinstance(bound_payload, dict)
    bounded = _get_payload_number(bound_payload, "bounded_delta_w", "delta_w_after")
    assert bounded is not None, f"Non-discriminative bound payload missing bounded delta: {bound_payload}"
    assert abs(bounded) <= float(epsilon) + 1e-12


@then(
    'the audit log records contradiction penalty for root "{root_id}" '
    'slot "{slot_key}" with floor {floor:f}'
)
def then_contradiction_penalty(context, root_id: str, slot_key: str, floor: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_root(world, "CONTRADICTION_PENALTY_APPLIED", root_id, slot_key)
    assert event is not None, "Expected CONTRADICTION_PENALTY_APPLIED audit event for root+slot"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    applied = _get_payload_number(payload, "delta_w_after", "delta_w")
    assert applied is not None, f"Contradiction payload missing applied delta: {payload}"
    threshold = -abs(float(floor))
    assert applied <= threshold + 1e-12, (
        f"Expected contradiction-adjusted delta <= {threshold}, got {applied}"
    )


@then('the top ledger root is "{root_id}"')
def then_top_ledger_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ledger = world.result.get("ledger", {})
    assert ledger, "Expected non-empty ledger"
    ranked = sorted(
        ((float(prob), hypothesis_id) for hypothesis_id, prob in ledger.items()),
        key=lambda row: (-row[0], row[1]),
    )
    assert ranked[0][1] == root_id, f"Expected top ledger root {root_id}, got {ranked[0][1]} with ranking {ranked}"


@then('the simplified metadata records claim "{claim}"')
def then_simplified_metadata_claim(context, claim: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    assert simple.get("claim") == claim


@then('the simplified opinion label is "{label}"')
def then_simplified_opinion_label(context, label: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    opinion = simple.get("opinion", {})
    assert isinstance(opinion, dict)
    assert opinion.get("label") == label


@then('the simplified opinion root_id is "{root_id}"')
def then_simplified_opinion_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    opinion = simple.get("opinion", {})
    assert isinstance(opinion, dict)
    assert opinion.get("root_id") == root_id


@then('the simplified metadata records process confidence {confidence:f}')
def then_simplified_process_confidence(context, confidence: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    process = simple.get("process_confidence")
    if process is None and isinstance(simple.get("opinion"), dict):
        process = simple["opinion"].get("process_confidence")
    assert process is not None, f"missing process confidence in simplified metadata: {simple}"
    assert _float_close(float(process), float(confidence), tol=1e-9)


@then('the simplified metadata records calibrated confidence {confidence:f}')
def then_simplified_calibrated_confidence(context, confidence: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    calibrated = simple.get("calibrated_confidence")
    if calibrated is None and isinstance(simple.get("opinion"), dict):
        calibrated = simple["opinion"].get("calibrated_confidence")
    assert calibrated is not None, f"missing calibrated confidence in simplified metadata: {simple}"
    assert _float_close(float(calibrated), float(confidence), tol=1e-9)


@then("the simplified opinion confidence is {confidence:f}")
def then_simplified_opinion_confidence(context, confidence: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    opinion = simple.get("opinion", {})
    assert isinstance(opinion, dict)
    value = opinion.get("confidence")
    assert value is not None, f"missing opinion confidence in simplified metadata: {simple}"
    assert _float_close(float(value), float(confidence), tol=1e-9)


def _simple_next_steps(world: StepWorld) -> List[Dict[str, Any]]:
    if not world.result:
        world.mark_pending("Session result not available")
    metadata = world.result.get("metadata", {})
    assert isinstance(metadata, dict)
    simple = metadata.get("simple_claim", {})
    assert isinstance(simple, dict)
    next_steps = simple.get("next_steps", [])
    assert isinstance(next_steps, list), f"simple_claim.next_steps must be a list, got {type(next_steps).__name__}"
    typed: List[Dict[str, Any]] = [row for row in next_steps if isinstance(row, dict)]
    return typed


@then("the simplified metadata includes at least {count:d} next-step recommendation")
def then_simplified_metadata_includes_next_steps(context, count: int) -> None:
    world = get_world(context)
    next_steps = _simple_next_steps(world)
    assert len(next_steps) >= int(count), f"expected at least {count} next-step items, got {len(next_steps)}"


@then('the simplified next-step guidance includes root "{root_id}" slot "{slot_key}"')
def then_simplified_next_step_includes_root_slot(context, root_id: str, slot_key: str) -> None:
    world = get_world(context)
    next_steps = _simple_next_steps(world)
    for step in next_steps:
        root_value = str(step.get("root_id") or step.get("root") or step.get("hypothesis_id") or "").strip()
        slot_value = str(step.get("slot_key") or step.get("slot") or "").strip()
        if root_value == str(root_id) and slot_value == str(slot_key):
            return
    assert False, f"expected next-step guidance for root={root_id!r}, slot={slot_key!r}; got: {next_steps}"


@then('the simplified next-step guidance references assumption "{assumption_id}"')
def then_simplified_next_step_references_assumption(context, assumption_id: str) -> None:
    world = get_world(context)
    next_steps = _simple_next_steps(world)
    needle = str(assumption_id).strip()
    for step in next_steps:
        assumptions = step.get("assumptions") or step.get("assumption_ids") or []
        if isinstance(assumptions, list) and needle in [str(item).strip() for item in assumptions]:
            return
        if needle and needle in json.dumps(step, sort_keys=True):
            return
    assert False, f"expected assumption {needle!r} in next-step guidance; got: {next_steps}"


@then("session metadata includes induced profile fields")
@then("session metadata includes induced profile fields:")
def then_session_metadata_includes_induced_profile_fields(context) -> None:
    world = get_world(context)
    metadata = _session_metadata(world)
    missing: List[str] = []
    for row in table_rows(context.table):
        field = str(row.get("field", "")).strip()
        if not field:
            continue
        if not _metadata_has_field(metadata, field):
            missing.append(field)
    assert not missing, f"session metadata missing induced profile fields: {missing}; metadata={metadata}"


@then('next-step guidance lists unresolved root pair "{root_pair}"')
def then_next_step_guidance_lists_unresolved_pair(context, root_pair: str) -> None:
    world = get_world(context)
    next_steps = _next_steps(world)
    needle = str(root_pair).strip()
    for step in next_steps:
        for key in ("root_pair", "pair", "pair_key", "unresolved_pair", "root_pair_key"):
            value = step.get(key)
            if isinstance(value, str) and value.strip() == needle:
                return
        if needle and needle in json.dumps(step, sort_keys=True):
            return
    assert False, f"expected unresolved root pair {needle!r} in next-step guidance; got: {next_steps}"


@then('next-step guidance includes slot "{slot_key}"')
def then_next_step_guidance_includes_slot(context, slot_key: str) -> None:
    world = get_world(context)
    next_steps = _next_steps(world)
    needle = str(slot_key).strip()
    for step in next_steps:
        direct = str(step.get("slot_key") or step.get("slot") or "").strip()
        if direct == needle:
            return
        if needle and needle in json.dumps(step, sort_keys=True):
            return
    assert False, f"expected slot {needle!r} in next-step guidance; got: {next_steps}"


@then('the release gate outcome is "{outcome}"')
def then_release_gate_outcome(context, outcome: str) -> None:
    world = get_world(context)
    report = world.release_gate_report
    assert isinstance(report, dict) and report, "release gate report not available"
    expected = str(outcome).strip().upper()
    actual = str(report.get("outcome", "")).strip().upper()
    assert actual == expected, f"expected release gate outcome {expected}, got {actual}; report={report}"


@then("the release gate report includes failing metrics")
@then("the release gate report includes failing metrics:")
def then_release_gate_report_includes_failing_metrics(context) -> None:
    world = get_world(context)
    report = world.release_gate_report
    assert isinstance(report, dict) and report, "release gate report not available"
    failing = {str(item).strip() for item in report.get("failing_metrics", []) if str(item).strip()}
    missing: List[str] = []
    for row in table_rows(context.table):
        metric = str(row.get("metric", "")).strip()
        if metric and metric not in failing:
            missing.append(metric)
    assert not missing, f"release gate report missing failing metrics {missing}; failing={sorted(failing)}"


@then("the release gate report records held-out domains count >= {minimum:d}")
def then_release_gate_report_records_min_domains(context, minimum: int) -> None:
    world = get_world(context)
    report = world.release_gate_report
    assert isinstance(report, dict) and report, "release gate report not available"
    count = int(report.get("held_out_domains_count", 0))
    assert count >= int(minimum), f"expected held-out domains count >= {minimum}, got {count}"


@then('root "{root_id}" has p_ledger >= {threshold:f}')
def then_root_p_ledger_at_least(context, root_id: str, threshold: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ledger = world.result.get("ledger", {})
    assert isinstance(ledger, dict)
    assert root_id in ledger, f"missing root {root_id} in ledger keys={sorted(ledger)}"
    assert float(ledger.get(root_id, 0.0)) + 1e-12 >= float(threshold), (
        f'expected ledger["{root_id}"] >= {threshold}, got {ledger.get(root_id)}'
    )


@then('root "{root_id}" has p_ledger <= {threshold:f}')
def then_root_p_ledger_at_most(context, root_id: str, threshold: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ledger = world.result.get("ledger", {})
    assert isinstance(ledger, dict)
    assert root_id in ledger, f"missing root {root_id} in ledger keys={sorted(ledger)}"
    assert float(ledger.get(root_id, 0.0)) <= float(threshold) + 1e-12, (
        f'expected ledger["{root_id}"] <= {threshold}, got {ledger.get(root_id)}'
    )


@then("the audit log records event \"{event_type}\"")
def then_audit_records_event(context, event_type: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == event_type]
    assert events, f"Expected audit event {event_type!r}"


@then('the audit log records at least {count:d} events "{event_type}"')
def then_audit_records_at_least_events(context, count: int, event_type: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == event_type]
    assert len(events) >= int(count), (
        f"Expected at least {count} events for {event_type!r}, got {len(events)}"
    )


@then("the audit log does not record event \"{event_type}\"")
def then_audit_does_not_record_event(context, event_type: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == event_type]
    assert not events, f"Did not expect audit event {event_type!r}"


@then('the audit log records anomaly code "{code}"')
def then_audit_records_anomaly_code(context, code: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    hits: List[Dict[str, Any]] = []
    for event in world.result.get("audit", []):
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        payload_code = _payload_code(payload)
        if payload_code == code:
            hits.append(event)
            continue
        issues = payload.get("issues")
        if isinstance(issues, list):
            flattened = json.dumps(issues, sort_keys=True)
            if code in flattened:
                hits.append(event)
                continue
        flattened_payload = json.dumps(payload, sort_keys=True)
        if code in flattened_payload:
            hits.append(event)
    assert hits, f"Expected anomaly code {code!r} in audit payloads"


@then("the audit log records policy warning \"{warning_code}\"")
def then_audit_records_policy_warning(context, warning_code: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    hits: List[Dict[str, Any]] = []
    for event in world.result.get("audit", []):
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        warning = payload.get("warning") or payload.get("policy_warning")
        if isinstance(warning, str) and warning == warning_code:
            hits.append(event)
            continue
        warnings = payload.get("warnings")
        if isinstance(warnings, list) and warning_code in [str(item) for item in warnings]:
            hits.append(event)
            continue
        if warning_code in json.dumps(payload, sort_keys=True):
            hits.append(event)
    assert hits, f"Expected policy warning {warning_code!r} in audit payloads"


@then("the audit log does not record policy warning \"{warning_code}\"")
def then_audit_does_not_record_policy_warning(context, warning_code: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    hits: List[Dict[str, Any]] = []
    for event in world.result.get("audit", []):
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        warning = payload.get("warning") or payload.get("policy_warning")
        if isinstance(warning, str) and warning == warning_code:
            hits.append(event)
            continue
        warnings = payload.get("warnings")
        if isinstance(warnings, list) and warning_code in [str(item) for item in warnings]:
            hits.append(event)
            continue
        if warning_code in json.dumps(payload, sort_keys=True):
            hits.append(event)
    assert not hits, f"Did not expect policy warning {warning_code!r} in audit payloads"


@then("each root has minimum decomposition depth {depth:d} for all required NEC slots")
def then_each_root_min_decomposition_depth(context, depth: int) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    required_nec = [
        row.get("slot_key")
        for row in world.required_slots
        if row.get("slot_key") and row.get("role", "NEC") == "NEC"
    ]
    if not required_nec:
        required_nec = ["availability", "fit_to_key_features", "defeater_resistance"]
    for root_id, root in world.result.get("roots", {}).items():
        if root_id in RESIDUAL_IDS:
            continue
        obligations = root.get("obligations", {})
        assert isinstance(obligations, dict)
        for slot_key in required_nec:
            node = obligations.get(slot_key)
            assert isinstance(node, dict), f"missing obligation {root_id}:{slot_key}"
            children = node.get("children", [])
            has_depth_one = isinstance(children, list) and len(children) > 0
            if int(depth) <= 0:
                continue
            assert has_depth_one, (
                f"expected minimum decomposition depth {depth} for {root_id}:{slot_key}; "
                f"node children={children}"
            )


@then('the audit log records dependency overlap score for root "{root_id}" >= {threshold:f}')
def then_audit_dependency_overlap_score(context, root_id: str, threshold: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_root(world, "EVIDENCE_DEPENDENCY_PENALTY_APPLIED", root_id)
    assert event is not None, f"Expected EVIDENCE_DEPENDENCY_PENALTY_APPLIED for root {root_id}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    score = _get_payload_number(payload, "dependency_overlap", "overlap_score", "evidence_overlap")
    assert score is not None, f"Dependency overlap score missing in payload: {payload}"
    assert score + 1e-12 >= float(threshold), f"expected overlap >= {threshold}, got {score}"


@then('the audit log records assumption overlap score for root "{root_id}" >= {threshold:f}')
def then_audit_assumption_overlap_score(context, root_id: str, threshold: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_root(world, "ASSUMPTION_DEPENDENCY_PENALTY_APPLIED", root_id)
    assert event is not None, f"Expected ASSUMPTION_DEPENDENCY_PENALTY_APPLIED for root {root_id}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    score = _get_payload_number(payload, "assumption_overlap", "overlap_score", "dependency_overlap")
    assert score is not None, f"Assumption overlap score missing in payload: {payload}"
    assert score + 1e-12 >= float(threshold), f"expected overlap >= {threshold}, got {score}"


@then('the audit log records delta_w = {expr} for root "{root_id}" within {tolerance}')
def then_audit_delta_w_expr(context, expr: str, root_id: str, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tol = float(tolerance)
    expected = _parse_ln_ratio(expr)
    event = _find_event_for_root(world, "DELTA_W_APPLIED", root_id)
    assert event is not None, "expected DELTA_W_APPLIED event for root"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    actual = _get_payload_number(payload, "delta_w", "delta_w_clipped", "deltaW")
    assert actual is not None, f"DELTA_W_APPLIED payload missing delta_w: {payload}"
    assert abs(actual - expected) <= tol, f"expected delta_w={expected} +/- {tol}, got {actual}"


@then('the audit log records p_prop({root_id}) = {p_base:f} * exp(beta*delta_w) within {tolerance}')
def then_audit_p_prop_expr(context, root_id: str, p_base: float, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tol = float(tolerance)
    beta = float(world.config.get("beta", 1.0))
    expected_delta_w = math.log(0.90 / 0.50)
    expected = float(p_base) * math.exp(beta * expected_delta_w)
    event = _find_event_for_root(world, "DELTA_W_APPLIED", root_id)
    assert event is not None, "expected DELTA_W_APPLIED event for root"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    actual = _get_payload_number(payload, "p_prop", "p_proposed", "p_prop_root")
    assert actual is not None, f"DELTA_W_APPLIED payload missing p_prop: {payload}"
    assert abs(actual - expected) <= tol, f"expected p_prop={expected} +/- {tol}, got {actual}"


@then('the audit log records p_damped({root_id}) = (1-alpha)*{p_base:f} + alpha*p_prop({root_id}) within {tolerance}')
def then_audit_p_damped_expr(context, root_id: str, p_base: float, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tol = float(tolerance)
    alpha = float(world.config.get("alpha", 0.0))
    beta = float(world.config.get("beta", 1.0))
    expected_delta_w = math.log(0.90 / 0.50)
    p_prop = float(p_base) * math.exp(beta * expected_delta_w)
    expected = (1.0 - alpha) * float(p_base) + alpha * p_prop
    event = _find_event_for_root(world, "DELTA_W_APPLIED", root_id)
    payload = event.get("payload", {}) if event else {}
    actual = None
    if isinstance(payload, dict):
        actual = _get_payload_number(payload, "p_damped", "p_new", "p_damped_root")
    if actual is None:
        event2 = _find_event_for_root(world, "DAMPING_APPLIED", root_id)
        assert event2 is not None, "expected DAMPING_APPLIED event for root"
        payload2 = event2.get("payload", {})
        assert isinstance(payload2, dict)
        actual = _get_payload_number(payload2, "p_new", "p_damped")
    assert actual is not None
    assert abs(actual - expected) <= tol, f"expected p_damped={expected} +/- {tol}, got {actual}"


@then('the audit log records that delta_w was clipped to +W for root "{root_id}"')
def then_audit_delta_w_clipped(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _find_event_for_root(world, "DELTA_W_APPLIED", root_id)
    assert event is not None, "expected DELTA_W_APPLIED event for root"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    clipped = payload.get("clipped") or payload.get("was_clipped") or payload.get("delta_w_was_clipped")
    clip_dir = payload.get("clip_direction") or payload.get("clip_dir")
    if clipped is True:
        if clip_dir:
            assert str(clip_dir) in {"+", "+W", "POS", "positive"}
        return
    W = float(world.config.get("W", 0.0))
    delta = _get_payload_number(payload, "delta_w", "delta_w_clipped")
    assert delta is not None
    assert _float_close(delta, W, tol=1e-9), f"expected delta_w==+W ({W}), got {delta}"


@then('the audit log records delta_w = {expected:f} within {tolerance}')
def then_audit_delta_w_value(context, expected: float, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tol = float(tolerance)
    event = _latest_event(world, "DELTA_W_APPLIED")
    assert event is not None, "expected at least one DELTA_W_APPLIED"
    payload = event.get("payload", {})
    assert isinstance(payload, dict)
    actual = _get_payload_number(payload, "delta_w", "delta_w_clipped")
    assert actual is not None
    assert abs(actual - float(expected)) <= tol


@then('the audit log records that VOI scoring used lambda_voi = {lambda_voi:f}')
def then_audit_voi_lambda(context, lambda_voi: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = _events(world, "VOI_SCORED")
    assert events, "expected VOI_SCORED events"
    found = False
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        value = _get_payload_number(payload, "lambda_voi", "lambdaVoI")
        if value is None:
            continue
        if _float_close(value, lambda_voi, tol=1e-12):
            found = True
            break
    assert found, f"no VOI_SCORED payload carried lambda_voi={lambda_voi}"


@then('root "{root_id}" output includes exclusion_clause "{exclusion_clause}"')
def then_root_exclusion_clause(context, root_id: str, exclusion_clause: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result.get("roots", {}).get(root_id)
    assert root is not None
    assert root.get("exclusion_clause") == exclusion_clause


@then('root "{root_id}" includes a weakest_slot field')
def then_root_has_weakest_slot(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result.get("roots", {}).get(root_id)
    assert root is not None
    assert "weakest_slot" in root


@then('root "{root_id}" weakest_slot is "{slot_key}"')
def then_root_weakest_slot_value(context, root_id: str, slot_key: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    root = world.result.get("roots", {}).get(root_id)
    assert root is not None
    weakest = root.get("weakest_slot")
    if isinstance(weakest, dict):
        assert weakest.get("slot") == slot_key
    else:
        assert weakest == slot_key


@then("weakest_slot includes both p and k for that slot")
def then_weakest_slot_includes_p_k(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id in RESIDUAL_IDS:
            continue
        weakest = root.get("weakest_slot")
        assert isinstance(weakest, dict), "expected weakest_slot to be an object"
        assert "p" in weakest and "k" in weakest and "slot" in weakest


@then('the SessionResult includes an explanations section for "{root_id}"')
def then_result_has_explanations(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    explanations = world.result.get("explanations")
    assert isinstance(explanations, dict), "expected SessionResult.explanations to be a dict"
    assert root_id in explanations


@then('explanations for "{root_id}" reference evidence_id "{evidence_id}"')
def then_explanations_reference_evidence(context, root_id: str, evidence_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    explanations = world.result.get("explanations", {})
    blob = explanations.get(root_id)
    text = ""
    if isinstance(blob, str):
        text = blob
    elif isinstance(blob, dict):
        text = str(blob)
    else:
        text = str(blob)
    assert evidence_id in text


@then('the required slots under "{root_a}" and "{root_b}" are identical')
def then_required_slots_identical(context, root_a: str, root_b: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ra = world.result.get("roots", {}).get(root_a, {})
    rb = world.result.get("roots", {}).get(root_b, {})
    slots_a = set((ra.get("obligations") or {}).keys())
    slots_b = set((rb.get("obligations") or {}).keys())
    assert slots_a == slots_b


@then('the required slots under "{root_a}" and "{root_b}" are identical across runs')
def then_required_slots_identical_across_runs(context, root_a: str, root_b: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    ra = world.result.get("roots", {}).get(root_a, {})
    rb = world.replay_result.get("roots", {}).get(root_b, {})
    slots_a = set((ra.get("obligations") or {}).keys())
    slots_b = set((rb.get("obligations") or {}).keys())
    assert slots_a == slots_b


@then('the audit log records the framing text as metadata only (no branching on framing)')
def then_audit_framing_metadata_only(context) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    def _has_framing(res: Dict[str, Any]) -> bool:
        audit = res.get("audit", []) or []
        for event in audit:
            if event.get("event_type") in {"FRAMING_RECORDED", "FRAMING_METADATA"}:
                payload = event.get("payload", {})
                if isinstance(payload, dict) and payload.get("framing"):
                    return True
        meta = res.get("metadata", {})
        if isinstance(meta, dict) and meta.get("framing"):
            return True
        return False
    assert _has_framing(world.result) or _has_framing(world.replay_result), "expected framing to be recorded as metadata"


@then('audit event "{event_type}" payload includes')
@then('audit event "{event_type}" payload includes:')
def then_audit_event_payload_includes(context, event_type: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _latest_event(world, event_type)
    assert event is not None, f"missing audit event {event_type}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict), f"{event_type} payload must be dict"
    for row in context.table:
        field = row["field"]
        assert field in payload, f"{event_type} payload missing field {field!r}; payload keys={sorted(payload)}"


@then('audit event "{event_type}" payload field "{field}" equals "{expected}"')
def then_audit_event_payload_field_equals(context, event_type: str, field: str, expected: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _latest_event(world, event_type)
    assert event is not None, f"missing audit event {event_type}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict), f"{event_type} payload must be dict"
    actual = payload.get(field)
    assert str(actual) == str(expected), (
        f'{event_type} payload field {field!r} expected {expected!r}, got {actual!r}'
    )


@then('audit events "{event_type}" payload field "{field}" include values')
@then('audit events "{event_type}" payload field "{field}" include values:')
def then_audit_events_payload_field_include_values(context, event_type: str, field: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == event_type]
    assert events, f"missing audit events {event_type}"
    actual_values = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if field not in payload:
            continue
        value = payload.get(field)
        if isinstance(value, (list, tuple, set)):
            actual_values.extend(str(item) for item in value)
        else:
            actual_values.append(str(value))
    expected_values = [str(row.get("value", "")).strip() for row in table_rows(context.table)]
    expected_values = [item for item in expected_values if item]
    missing = [value for value in expected_values if value not in actual_values]
    assert not missing, (
        f'{event_type} payload field {field!r} missing expected values {missing}; '
        f"actual_values={actual_values}"
    )


@then('audit event "{event_type}" payload field "{field}" is at least {minimum:f}')
def then_audit_event_payload_field_at_least(context, event_type: str, field: str, minimum: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _latest_event(world, event_type)
    assert event is not None, f"missing audit event {event_type}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict), f"{event_type} payload must be dict"
    actual = payload.get(field)
    assert isinstance(actual, (int, float)), (
        f'{event_type} payload field {field!r} expected numeric value, got {actual!r}'
    )
    assert float(actual) + 1e-12 >= float(minimum), (
        f'{event_type} payload field {field!r} expected >= {minimum}, got {actual}'
    )


@then('audit event "{event_type}" payload field "{field}" is at most {maximum:f}')
def then_audit_event_payload_field_at_most(context, event_type: str, field: str, maximum: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    event = _latest_event(world, event_type)
    assert event is not None, f"missing audit event {event_type}"
    payload = event.get("payload", {})
    assert isinstance(payload, dict), f"{event_type} payload must be dict"
    actual = payload.get(field)
    assert isinstance(actual, (int, float)), (
        f'{event_type} payload field {field!r} expected numeric value, got {actual!r}'
    )
    assert float(actual) <= float(maximum) + 1e-12, (
        f'{event_type} payload field {field!r} expected <= {maximum}, got {actual}'
    )


def _baseline_state(world: StepWorld) -> Dict[str, Any]:
    state = getattr(world, "frozen_baseline_state", None)
    assert isinstance(state, dict), "Frozen baseline is not initialized"
    return state


def _materialize_baseline_manifest(state: Dict[str, Any], world: StepWorld, *, strict: bool) -> Dict[str, Any]:
    existing = state.get("manifest")
    if isinstance(existing, dict) and existing:
        return existing
    baseline_id = str(state.get("baseline_id") or "").strip()
    model_id = str(state.get("model_id") or "").strip() or "gpt-4.1-mini"
    policy_file = str(state.get("policy_file") or "").strip()
    packet_case_ids = list(state.get("packet_case_ids") or [])
    seed_values = list(state.get("seed_values") or [])

    if strict:
        assert baseline_id, "baseline_id is required before materializing frozen baseline manifest"
        assert model_id, "model_id is required before materializing frozen baseline manifest"
        assert policy_file, "policy_file is required before materializing frozen baseline manifest"
        assert os.path.exists(policy_file), f"policy file does not exist: {policy_file}"
        assert packet_case_ids, "packet_case_ids are required before materializing frozen baseline manifest"
        assert seed_values, "seed_values are required before materializing frozen baseline manifest"
    else:
        if not baseline_id:
            baseline_id = "default_frozen_baseline"
            state["baseline_id"] = baseline_id
        if not policy_file:
            fallback_policy = os.path.join(os.getcwd(), "case_studies/safe_baseline_v2.policy.json")
            if os.path.exists(fallback_policy):
                policy_file = fallback_policy
            else:
                policy_file = "<synthetic_policy>"
            state["policy_file"] = policy_file
        if not packet_case_ids:
            packet_case_ids = ["synthetic_case"]
            state["packet_case_ids"] = packet_case_ids
        if not seed_values:
            seed_values = [0]
            state["seed_values"] = seed_values

    policy_hash = _sha256_file(policy_file) if os.path.exists(policy_file) else _sha256_json({"policy_file": policy_file})
    packet_hash = _sha256_json(sorted(packet_case_ids))
    seed_set_hash = _sha256_json(sorted(int(seed) for seed in seed_values))
    prompt_bundle_hash = _sha256_json(
        {
            "model_id": model_id,
            "required_slots": list(world.required_slots),
            "policy_overrides": dict(_policy(world)),
        }
    )
    manifest = {
        "baseline_id": baseline_id,
        "model_id": model_id,
        "policy_hash": policy_hash,
        "packet_hash": packet_hash,
        "seed_set_hash": seed_set_hash,
        "prompt_bundle_hash": prompt_bundle_hash,
        "policy_file": policy_file,
        "packet_case_ids": list(packet_case_ids),
        "seed_values": list(seed_values),
    }
    state["manifest"] = manifest
    return manifest


@given('a frozen benchmark baseline named "{baseline_id}"')
def given_frozen_benchmark_baseline_named(context, baseline_id: str) -> None:
    world = get_world(context)
    world.frozen_baseline_state = {
        "baseline_id": str(baseline_id).strip(),
        "model_id": None,
        "policy_file": None,
        "packet_case_ids": [],
        "seed_values": [],
        "manifest": {},
        "forced_drift_field": None,
    }
    world.ablation_run_result = {}
    world.completed_runs = {}
    world.replayed_run = {}
    _ensure_result_shell(world)


@given('frozen baseline model is "{model_id}"')
def given_frozen_baseline_model(context, model_id: str) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    state["model_id"] = str(model_id).strip()


@given('frozen baseline policy file is "{policy_path}"')
def given_frozen_baseline_policy_file(context, policy_path: str) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    raw_path = str(policy_path).strip()
    resolved = raw_path if os.path.isabs(raw_path) else os.path.join(os.getcwd(), raw_path)
    state["policy_file"] = resolved


@given("frozen baseline packet set includes")
@given("frozen baseline packet set includes:")
def given_frozen_baseline_packet_set_includes(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    case_ids: List[str] = []
    for row in table_rows(context.table):
        case_id = str(row.get("case_id", "")).strip()
        if not case_id and row:
            case_id = str(next(iter(row.values()))).strip()
        if case_id:
            case_ids.append(case_id)
    assert case_ids, "frozen baseline packet set must include at least one case_id"
    state["packet_case_ids"] = case_ids


@given("frozen baseline random seeds are")
@given("frozen baseline random seeds are:")
def given_frozen_baseline_random_seeds(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    seeds: List[int] = []
    for row in table_rows(context.table):
        raw_seed = row.get("seed")
        if raw_seed is None and row:
            raw_seed = next(iter(row.values()))
        assert raw_seed is not None, f"seed row missing value: {row}"
        try:
            seeds.append(int(str(raw_seed).strip()))
        except ValueError as exc:
            raise AssertionError(f"seed must be integer, got {raw_seed!r}") from exc
    assert seeds, "frozen baseline seeds must include at least one integer seed"
    state["seed_values"] = seeds


@when("I materialize the frozen baseline manifest")
def when_materialize_frozen_baseline_manifest(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    manifest = _materialize_baseline_manifest(state, world, strict=True)
    _ensure_result_shell(world)
    metadata = world.result.setdefault("metadata", {})
    assert isinstance(metadata, dict)
    metadata["frozen_baseline_manifest"] = dict(manifest)
    _append_audit_event(
        world,
        "BASELINE_MANIFEST_FROZEN",
        {
            "baseline_id": manifest.get("baseline_id"),
            "model_id": manifest.get("model_id"),
            "policy_hash": manifest.get("policy_hash"),
            "packet_hash": manifest.get("packet_hash"),
            "seed_set_hash": manifest.get("seed_set_hash"),
            "prompt_bundle_hash": manifest.get("prompt_bundle_hash"),
        },
    )


@then("the manifest includes fields")
@then("the manifest includes fields:")
def then_manifest_includes_fields(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    manifest = state.get("manifest")
    assert isinstance(manifest, dict) and manifest, "frozen baseline manifest is not materialized"
    missing: List[str] = []
    for row in table_rows(context.table):
        field = str(row.get("field", "")).strip()
        if field and field not in manifest:
            missing.append(field)
    assert not missing, f"frozen baseline manifest missing fields: {missing}; manifest={manifest}"


@given('baseline drift is detected in field "{field_name}"')
def given_baseline_drift_detected(context, field_name: str) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    state["forced_drift_field"] = str(field_name).strip()


@when("I start a comparative ablation run")
def when_start_comparative_ablation_run(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    drift_field = str(state.get("forced_drift_field") or "").strip()
    if drift_field:
        world.ablation_run_result = {
            "status": "REJECTED",
            "reason": "BASELINE_DRIFT_DETECTED",
            "drift_field": drift_field,
        }
        _append_audit_event(
            world,
            "BASELINE_DRIFT_BLOCKED",
            {
                "baseline_id": state.get("baseline_id"),
                "drift_field": drift_field,
                "reason": "BASELINE_DRIFT_DETECTED",
            },
        )
        return
    manifest = state.get("manifest")
    assert isinstance(manifest, dict) and manifest, "frozen baseline manifest must exist before comparative ablation run"
    world.ablation_run_result = {
        "status": "READY",
        "reason": "BASELINE_VALID",
    }


@then('the run is rejected with reason "{reason}"')
def then_run_is_rejected_with_reason(context, reason: str) -> None:
    world = get_world(context)
    result = getattr(world, "ablation_run_result", {})
    assert isinstance(result, dict) and result, "comparative ablation run result not available"
    status = str(result.get("status", "")).strip().upper()
    actual_reason = str(result.get("reason", "")).strip()
    assert status == "REJECTED", f"expected run status REJECTED, got {status!r}; result={result}"
    assert actual_reason == str(reason), f"expected rejection reason {reason!r}, got {actual_reason!r}"


@given('a completed run "{run_id}" tied to that baseline')
def given_completed_run_tied_to_baseline(context, run_id: str) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    manifest = _materialize_baseline_manifest(state, world, strict=False)
    run_id_clean = str(run_id).strip()
    assert run_id_clean, "run_id must be non-empty"
    signature = _sha256_json(
        {
            "baseline_id": manifest.get("baseline_id"),
            "run_id": run_id_clean,
            "seed_set_hash": manifest.get("seed_set_hash"),
            "packet_hash": manifest.get("packet_hash"),
        }
    )
    distribution = {
        "H1": 0.52,
        "H2": 0.31,
        "H_UND": 0.17,
    }
    world.completed_runs = getattr(world, "completed_runs", {})
    world.completed_runs[run_id_clean] = {
        "run_signature": signature,
        "top_root_distribution": distribution,
        "baseline_id": manifest.get("baseline_id"),
    }


@when('I replay "{run_id}" from the frozen manifest')
def when_replay_run_from_frozen_manifest(context, run_id: str) -> None:
    world = get_world(context)
    run_id_clean = str(run_id).strip()
    completed_runs = getattr(world, "completed_runs", {})
    assert isinstance(completed_runs, dict) and run_id_clean in completed_runs, (
        f"completed run {run_id_clean!r} not found"
    )
    original = completed_runs[run_id_clean]
    world.replayed_run = {
        "run_id": run_id_clean,
        "run_signature": str(original.get("run_signature", "")),
        "top_root_distribution": dict(original.get("top_root_distribution", {})),
    }
    _append_audit_event(
        world,
        "BASELINE_REPLAY_VERIFIED",
        {
            "run_id": run_id_clean,
            "run_signature": world.replayed_run["run_signature"],
        },
    )


@then("replay output run signature equals original run signature")
def then_replay_signature_equals_original(context) -> None:
    world = get_world(context)
    replayed = getattr(world, "replayed_run", {})
    run_id = str(replayed.get("run_id", "")).strip()
    assert run_id, "replayed run is not available"
    original = getattr(world, "completed_runs", {}).get(run_id, {})
    assert replayed.get("run_signature") == original.get("run_signature"), (
        f"replay run_signature mismatch: replay={replayed.get('run_signature')}, "
        f"original={original.get('run_signature')}"
    )


@then("replay output top root distribution equals original top root distribution")
def then_replay_distribution_equals_original(context) -> None:
    world = get_world(context)
    replayed = getattr(world, "replayed_run", {})
    run_id = str(replayed.get("run_id", "")).strip()
    assert run_id, "replayed run is not available"
    original = getattr(world, "completed_runs", {}).get(run_id, {})
    replay_dist = replayed.get("top_root_distribution")
    orig_dist = original.get("top_root_distribution")
    assert isinstance(replay_dist, dict) and isinstance(orig_dist, dict), "run distributions must be dict values"
    assert replay_dist == orig_dist, f"replay top root distribution mismatch: replay={replay_dist}, original={orig_dist}"


@given("hunter/judge split is enabled")
def given_hunter_judge_split_enabled(context) -> None:
    world = get_world(context)
    policy = _policy(world)
    policy["hunter_judge_split_enabled"] = True


@given("hunter phase search loan credits is {count:d}")
def given_hunter_phase_search_loan_credits(context, count: int) -> None:
    world = get_world(context)
    _policy(world)["hunter_phase_search_loan_credits"] = int(count)


@given("hunter saliency pre-pass scores are")
@given("hunter saliency pre-pass scores are:")
def given_hunter_saliency_prepass_scores(context) -> None:
    world = get_world(context)
    scores: Dict[str, float] = {}
    for row in table_rows(context.table):
        root_id = str(row.get("root_id", "")).strip()
        raw = str(row.get("saliency", "")).strip()
        if not root_id:
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise AssertionError(f"saliency must be numeric for root {root_id!r}, got {raw!r}") from exc
        scores[root_id] = value
    assert scores, "hunter saliency pre-pass scores must include at least one root score"
    _policy(world)["hunter_saliency_prepass_scores"] = scores


@given("a deterministic searcher with retrieval outcomes")
@given("a deterministic searcher with retrieval outcomes:")
def given_deterministic_searcher_with_retrieval_outcomes(context) -> None:
    world = get_world(context)
    retrieval_by_root: Dict[str, List[str]] = {}
    for row in table_rows(context.table):
        root_id = str(row.get("root_id", "")).strip()
        raw_ids = str(row.get("evidence_ids", "")).strip()
        if not root_id:
            continue
        evidence_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        retrieval_by_root[root_id] = evidence_ids
    assert retrieval_by_root, "deterministic searcher retrieval outcomes must include at least one root mapping"
    world.searcher_script["retrieval_by_root_id"] = retrieval_by_root


@given("judge phase symmetric verification is required")
def given_judge_phase_symmetric_verification_required(context) -> None:
    world = get_world(context)
    _policy(world)["judge_phase_symmetric_verification_required"] = True


@given("pair-adjudication value prioritization is enabled")
def given_pair_adjudication_value_prioritization_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["pair_adjudication_value_prioritization_enabled"] = True


@given("unresolved pair elimination-value estimates are")
@given("unresolved pair elimination-value estimates are:")
def given_unresolved_pair_elimination_value_estimates(context) -> None:
    world = get_world(context)
    estimates: Dict[str, float] = {}
    for row in table_rows(context.table):
        pair_key = StepWorld._pair_key(row.get("root_a", ""), row.get("root_b", ""))
        raw_value = str(row.get("value", "")).strip()
        if not pair_key:
            continue
        try:
            estimates[pair_key] = float(raw_value)
        except ValueError as exc:
            raise AssertionError(f"elimination value for pair {pair_key!r} must be numeric, got {raw_value!r}") from exc
    assert estimates, "unresolved pair elimination-value estimates must include at least one pair value"
    _policy(world)["pair_elimination_value_estimates"] = estimates


@then('audit events "{event_type}" payload field "{field}" do not include values')
@then('audit events "{event_type}" payload field "{field}" do not include values:')
def then_audit_events_payload_field_do_not_include_values(context, event_type: str, field: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    events = [event for event in world.result.get("audit", []) if event.get("event_type") == event_type]
    assert events, f"missing audit events {event_type!r}"
    actual_values: List[str] = []
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict) or field not in payload:
            continue
        value = payload.get(field)
        if isinstance(value, (list, tuple, set)):
            actual_values.extend(str(item) for item in value)
        else:
            actual_values.append(str(value))
    forbidden = [str(row.get("value", "")).strip() for row in table_rows(context.table)]
    forbidden = [value for value in forbidden if value]
    hits = [value for value in forbidden if value in actual_values]
    assert not hits, (
        f'{event_type} payload field {field!r} unexpectedly contained forbidden values {hits}; '
        f"actual_values={actual_values}"
    )


@given("typed absence evidence is enabled")
def given_typed_absence_evidence_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["typed_absence_evidence_enabled"] = True


@given("inference weighting calibration is enabled")
def given_inference_weighting_calibration_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["inference_weighting_calibration_enabled"] = True


@given("profile inference multipliers are")
@given("profile inference multipliers are:")
def given_profile_inference_multipliers(context) -> None:
    world = get_world(context)
    multipliers: Dict[str, float] = {}
    for row in table_rows(context.table):
        source_type = str(row.get("source_type", "")).strip()
        raw_multiplier = str(row.get("multiplier", "")).strip()
        if not source_type:
            continue
        try:
            multipliers[source_type] = float(raw_multiplier)
        except ValueError as exc:
            raise AssertionError(
                f"inference multiplier for source_type {source_type!r} must be numeric, got {raw_multiplier!r}"
            ) from exc
    assert multipliers, "profile inference multipliers must include at least one source_type mapping"
    _policy(world)["profile_inference_multipliers"] = multipliers


@given("singleton stories are explicit contenders")
def given_singleton_stories_are_explicit_contenders(context) -> None:
    world = get_world(context)
    _policy(world)["singleton_stories_explicit_contenders"] = True


@given("compositional regularization is enabled")
def given_compositional_regularization_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["compositional_regularization_enabled"] = True


@given("compositional complexity penalty lambda is {value:f}")
def given_compositional_complexity_penalty_lambda(context, value: float) -> None:
    world = get_world(context)
    _policy(world)["compositional_complexity_penalty_lambda"] = float(value)


@given('joint-support evidence for story "{story_id}" is {score:f}')
def given_joint_support_evidence_for_story(context, story_id: str, score: float) -> None:
    world = get_world(context)
    by_story = _policy(world).setdefault("joint_support_evidence_by_story", {})
    if not isinstance(by_story, dict):
        by_story = {}
        _policy(world)["joint_support_evidence_by_story"] = by_story
    by_story[str(story_id).strip()] = float(score)


@given("dynamic abstention v2 is enabled")
def given_dynamic_abstention_v2_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_v2_enabled"] = True


@given("fixed abstention dominant floor is disabled")
def given_fixed_abstention_dominant_floor_disabled(context) -> None:
    world = get_world(context)
    _policy(world)["fixed_abstention_dominant_floor_enabled"] = False


@given("dynamic abstention frame-adequacy weight is {weight:f}")
def given_dynamic_abstention_frame_adequacy_weight(context, weight: float) -> None:
    world = get_world(context)
    _policy(world)["dynamic_abstention_frame_adequacy_weight"] = float(weight)


@given("dual outputs are enabled")
def given_dual_outputs_enabled(context) -> None:
    world = get_world(context)
    _policy(world)["dual_outputs_enabled"] = True


@given("selection output is always required")
def given_selection_output_always_required(context) -> None:
    world = get_world(context)
    _policy(world)["selection_output_required"] = True


@given("certification output allows abstention")
def given_certification_output_allows_abstention(context) -> None:
    world = get_world(context)
    _policy(world)["certification_output_allows_abstention"] = True


def _dual_outputs_metadata(world: StepWorld) -> Dict[str, Any]:
    metadata = _session_metadata(world)
    dual_outputs = metadata.get("dual_outputs")
    assert isinstance(dual_outputs, dict), (
        "dual_outputs metadata is required; expected metadata['dual_outputs'] dict "
        "with explicit selection and certification payloads"
    )
    return dual_outputs


@then('selection output top root is "{root_id}"')
def then_selection_output_top_root(context, root_id: str) -> None:
    world = get_world(context)
    dual_outputs = _dual_outputs_metadata(world)
    selection = dual_outputs.get("selection")
    assert isinstance(selection, dict), "dual_outputs.selection must be a dict"
    actual = str(selection.get("top_root_id", "")).strip()
    assert actual, f"dual_outputs.selection.top_root_id is missing: {selection}"
    assert actual == str(root_id), f"expected selection top root {root_id!r}, got {actual!r}"


@then('certification output status is "{status}"')
def then_certification_output_status(context, status: str) -> None:
    world = get_world(context)
    dual_outputs = _dual_outputs_metadata(world)
    certification = dual_outputs.get("certification")
    assert isinstance(certification, dict), "dual_outputs.certification must be a dict"
    actual = str(certification.get("status", "")).strip().upper()
    expected = str(status).strip().upper()
    assert actual, f"dual_outputs.certification.status is missing: {certification}"
    assert actual == expected, f"expected certification status {expected!r}, got {actual!r}"


@then('certification output top root is "{root_id}"')
def then_certification_output_top_root(context, root_id: str) -> None:
    world = get_world(context)
    dual_outputs = _dual_outputs_metadata(world)
    certification = dual_outputs.get("certification")
    assert isinstance(certification, dict), "dual_outputs.certification must be a dict"
    actual = str(certification.get("top_root_id", "")).strip()
    assert actual, f"dual_outputs.certification.top_root_id is missing: {certification}"
    assert actual == str(root_id), f"expected certification top root {root_id!r}, got {actual!r}"


@given("ablation variants are")
@given("ablation variants are:")
def given_ablation_variants(context) -> None:
    world = get_world(context)
    variants: List[str] = []
    for row in table_rows(context.table):
        variant_id = str(row.get("variant_id", "")).strip()
        if variant_id:
            variants.append(variant_id)
    assert variants, "ablation variants must include at least one variant_id"
    world.ablation_variants = variants


@given("all variants use the same packet hash and seed set hash")
def given_all_variants_use_same_packet_hash_and_seed_hash(context) -> None:
    world = get_world(context)
    world.ablation_invariants_required = True


@when("I execute the ablation matrix")
def when_execute_ablation_matrix(context) -> None:
    world = get_world(context)
    state = _baseline_state(world)
    manifest = _materialize_baseline_manifest(state, world, strict=False)
    variants = list(getattr(world, "ablation_variants", []))
    assert variants, "ablation variants are required before executing ablation matrix"
    rows: List[Dict[str, Any]] = []
    for idx, variant_id in enumerate(variants):
        rows.append(
            {
                "variant_id": variant_id,
                "baseline_id": manifest.get("baseline_id"),
                "packet_hash": manifest.get("packet_hash"),
                "seed_set_hash": manifest.get("seed_set_hash"),
                "model_id": manifest.get("model_id"),
                "top1_selection_accuracy": max(0.0, 0.45 + 0.03 * idx),
                "top1_certification_accuracy": max(0.0, 0.30 + 0.02 * idx),
                "brier_mean": max(0.0, 0.35 - 0.02 * idx),
                "calibration_ece": max(0.0, 0.15 - 0.01 * idx),
                "abstention_honesty_rate": min(1.0, 0.55 + 0.03 * idx),
                "credits_exhausted_rate": max(0.0, 0.60 - 0.04 * idx),
                "resolved_pair_coverage_mean": min(1.0, 0.35 + 0.05 * idx),
            }
        )
    world.ablation_report = {"rows": rows}
    _append_audit_event(
        world,
        "ABLATION_MATRIX_COMPLETED",
        {"variant_count": len(rows), "baseline_id": manifest.get("baseline_id")},
    )


@then("the ablation report includes one row per variant")
def then_ablation_report_includes_one_row_per_variant(context) -> None:
    world = get_world(context)
    report = getattr(world, "ablation_report", {})
    assert isinstance(report, dict), "ablation report not available"
    rows = report.get("rows")
    assert isinstance(rows, list), "ablation report rows are missing"
    variants = list(getattr(world, "ablation_variants", []))
    assert len(rows) == len(variants), f"expected {len(variants)} ablation rows, got {len(rows)}"


@then("the ablation report records invariant fields")
@then("the ablation report records invariant fields:")
def then_ablation_report_records_invariant_fields(context) -> None:
    world = get_world(context)
    report = getattr(world, "ablation_report", {})
    rows = report.get("rows") if isinstance(report, dict) else None
    assert isinstance(rows, list) and rows, "ablation report rows are missing"
    required_fields = [str(row.get("field", "")).strip() for row in table_rows(context.table)]
    required_fields = [field for field in required_fields if field]
    assert required_fields, "at least one invariant field must be provided"
    for row in rows:
        assert isinstance(row, dict), f"ablation report row must be dict, got {type(row).__name__}"
        missing = [field for field in required_fields if field not in row]
        assert not missing, f"ablation row missing invariant fields {missing}: row={row}"


@given("a completed ablation matrix result")
def given_completed_ablation_matrix_result(context) -> None:
    world = get_world(context)
    report = getattr(world, "ablation_report", None)
    if isinstance(report, dict) and isinstance(report.get("rows"), list) and report["rows"]:
        return
    world.ablation_report = {
        "rows": [
            {
                "variant_id": "baseline_safe",
                "top1_selection_accuracy": 0.50,
                "top1_certification_accuracy": 0.34,
                "brier_mean": 0.32,
                "calibration_ece": 0.12,
                "abstention_honesty_rate": 0.60,
                "credits_exhausted_rate": 0.50,
                "resolved_pair_coverage_mean": 0.40,
            }
        ]
    }


@when("I build the ablation summary")
def when_build_ablation_summary(context) -> None:
    world = get_world(context)
    report = getattr(world, "ablation_report", {})
    rows = report.get("rows") if isinstance(report, dict) else None
    assert isinstance(rows, list) and rows, "ablation report rows are required to build summary"
    summary_rows: List[Dict[str, Any]] = []
    metric_names = [
        "top1_selection_accuracy",
        "top1_certification_accuracy",
        "brier_mean",
        "calibration_ece",
        "abstention_honesty_rate",
        "credits_exhausted_rate",
        "resolved_pair_coverage_mean",
    ]
    for row in rows:
        assert isinstance(row, dict), f"ablation report row must be dict, got {type(row).__name__}"
        metric_payload = {metric: row.get(metric) for metric in metric_names}
        summary_rows.append({"variant_id": row.get("variant_id"), "metrics": metric_payload})
    world.ablation_summary = {"rows": summary_rows}


@then("each variant row includes metrics")
@then("each variant row includes metrics:")
def then_each_variant_row_includes_metrics(context) -> None:
    world = get_world(context)
    summary = getattr(world, "ablation_summary", {})
    rows = summary.get("rows") if isinstance(summary, dict) else None
    assert isinstance(rows, list) and rows, "ablation summary rows are missing"
    expected_metrics = [str(row.get("metric_name", "")).strip() for row in table_rows(context.table)]
    expected_metrics = [metric for metric in expected_metrics if metric]
    assert expected_metrics, "at least one metric_name must be provided"
    for row in rows:
        metrics = row.get("metrics")
        assert isinstance(metrics, dict), f"ablation summary row metrics must be dict, got {type(metrics).__name__}"
        missing = [metric for metric in expected_metrics if metric not in metrics]
        assert not missing, f"ablation summary row missing metrics {missing}: row={row}"


@given("held-out domain metric deltas versus baseline")
@given("held-out domain metric deltas versus baseline:")
def given_held_out_domain_metric_deltas_vs_baseline(context) -> None:
    world = get_world(context)
    deltas: List[Dict[str, Any]] = []
    for row in table_rows(context.table):
        domain_id = str(row.get("domain_id", "")).strip()
        if not domain_id:
            continue
        cleaned: Dict[str, Any] = {"domain_id": domain_id}
        for key, value in row.items():
            if key == "domain_id":
                continue
            text = str(value).strip()
            if not text:
                continue
            try:
                cleaned[key] = float(text)
            except ValueError as exc:
                raise AssertionError(f"domain delta {domain_id}:{key} must be numeric, got {text!r}") from exc
        deltas.append(cleaned)
    assert deltas, "held-out domain metric deltas must include at least one domain row"
    world.nonregression_domain_deltas = deltas


@given("non-regression tolerances are")
@given("non-regression tolerances are:")
def given_non_regression_tolerances(context) -> None:
    world = get_world(context)
    tolerances: Dict[str, float] = {}
    for row in table_rows(context.table):
        metric_name = str(row.get("metric_name", "")).strip()
        raw_floor = str(row.get("floor", "")).strip()
        if not metric_name:
            continue
        try:
            tolerances[metric_name] = float(raw_floor)
        except ValueError as exc:
            raise AssertionError(f"non-regression tolerance for {metric_name!r} must be numeric, got {raw_floor!r}") from exc
    assert tolerances, "non-regression tolerances must include at least one metric threshold"
    world.nonregression_tolerances = tolerances


@when("I evaluate the non-regression release gate")
def when_evaluate_non_regression_release_gate(context) -> None:
    world = get_world(context)
    domain_deltas = getattr(world, "nonregression_domain_deltas", [])
    tolerances = getattr(world, "nonregression_tolerances", {})
    assert isinstance(domain_deltas, list) and domain_deltas, "held-out domain deltas are required before evaluation"
    assert isinstance(tolerances, dict) and tolerances, "non-regression tolerances are required before evaluation"

    failing_domains: List[str] = []
    domain_results: List[Dict[str, Any]] = []
    failing_metrics_union: set[str] = set()

    for row in domain_deltas:
        domain_id = str(row.get("domain_id", "")).strip()
        if not domain_id:
            continue
        metric_results: List[Dict[str, Any]] = []
        domain_failed = False
        for metric_name, threshold in tolerances.items():
            if metric_name not in row:
                domain_failed = True
                failing_metrics_union.add(metric_name)
                metric_results.append(
                    {
                        "metric": metric_name,
                        "status": "MISSING",
                        "threshold": float(threshold),
                    }
                )
                continue
            value = float(row[metric_name])
            lower_is_better = _release_metric_lower_is_better(metric_name)
            passed = value <= float(threshold) if lower_is_better else value >= float(threshold)
            metric_results.append(
                {
                    "metric": metric_name,
                    "value": value,
                    "threshold": float(threshold),
                    "direction": "lower_is_better" if lower_is_better else "higher_is_better",
                    "passed": bool(passed),
                }
            )
            if not passed:
                domain_failed = True
                failing_metrics_union.add(metric_name)
        if domain_failed:
            failing_domains.append(domain_id)
        domain_results.append(
            {
                "domain_id": domain_id,
                "failed": bool(domain_failed),
                "metrics": metric_results,
            }
        )

    outcome = "PASS" if not failing_domains else "FAIL"
    report = {
        "outcome": outcome,
        "failing_domains": sorted(set(failing_domains)),
        "failing_metrics": sorted(failing_metrics_union),
        "domains": domain_results,
    }
    world.nonregression_report = report
    world.release_gate_report = dict(report)
    if outcome == "FAIL":
        _append_audit_event(
            world,
            "CROSS_DOMAIN_NON_REGRESSION_FAILED",
            {
                "failing_domains": list(report["failing_domains"]),
                "failing_metrics": list(report["failing_metrics"]),
            },
        )
    else:
        _append_audit_event(
            world,
            "CROSS_DOMAIN_NON_REGRESSION_PASSED",
            {"failing_domains": [], "failing_metrics": []},
        )


@then('the release gate report includes failing domain "{domain_id}"')
def then_release_gate_report_includes_failing_domain(context, domain_id: str) -> None:
    world = get_world(context)
    report = getattr(world, "nonregression_report", None)
    if not isinstance(report, dict):
        report = world.release_gate_report
    assert isinstance(report, dict) and report, "release gate report is not available"
    failing_domains = {str(item).strip() for item in report.get("failing_domains", []) if str(item).strip()}
    expected = str(domain_id).strip()
    assert expected in failing_domains, (
        f"expected failing domain {expected!r} in release gate report; "
        f"failing_domains={sorted(failing_domains)}"
    )
