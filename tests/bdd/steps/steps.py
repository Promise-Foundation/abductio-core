from __future__ import annotations

from typing import Any, Dict, List

from behave import given, then, when

from abductio_core.application.canonical import canonical_id_for_statement
from tests.bdd.steps.support.step_world import StepWorld


def get_world(context) -> StepWorld:
    if not hasattr(context, "world"):
        context.world = StepWorld()
    return context.world


def table_key_values(table) -> Dict[str, str]:
    pairs: Dict[str, str] = {}
    for row in table:
        key = row.cells[0]
        value = row.cells[1]
        pairs[key] = value
    return pairs


def table_rows(table) -> List[Dict[str, str]]:
    return [dict(row.items()) for row in table]


@given("default config:")
def given_default_config(context) -> None:
    world = get_world(context)
    world.set_config(table_key_values(context.table))


@given("required template slots:")
def given_required_template_slots(context) -> None:
    world = get_world(context)
    world.set_required_slots(table_rows(context.table))


@given("a hypothesis set with named roots:")
def given_named_roots(context) -> None:
    world = get_world(context)
    world.set_roots(table_rows(context.table))


@given("hypothesis set A with named roots:")
def given_named_roots_a(context) -> None:
    world = get_world(context)
    world.set_roots_a(table_rows(context.table))


@given("hypothesis set B with the same roots but reversed ordering")
def given_named_roots_b(context) -> None:
    world = get_world(context)
    world.roots_b = list(reversed(world.roots_a))


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


@given('a deterministic decomposer that fails to scope root "{root_id}"')
def given_decomposer_fail_root(context, root_id: str) -> None:
    world = get_world(context)
    world.set_decomposer_fail_root(root_id)


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


@given('a deterministic evaluator that returns for node "{node_key}":')
def given_deterministic_evaluator_node(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator with the following outcomes:")
def given_deterministic_evaluator_outcomes(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator that returns:")
def given_deterministic_evaluator_returns(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator returns:")
def given_deterministic_evaluator_returns_alt(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes(table_rows(context.table))


@given('a deterministic evaluator that attempts to set for node "{node_key}":')
def given_deterministic_evaluator_attempts(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator that returns rubric:")
def given_deterministic_evaluator_rubric(context) -> None:
    world = get_world(context)
    world.set_rubric({key: int(value) for key, value in table_key_values(context.table).items()})


@given("a deterministic evaluator with at least one evaluation outcome")
def given_deterministic_evaluator_one(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes([{"node_key": "placeholder", "p": "0.5"}])


@given('credits {credits:d}')
def given_credits(context, credits: int) -> None:
    world = get_world(context)
    world.set_credits(credits)


@given('the root "{root_id}" is already SCOPED with all slots having k >= {k_min:f}')
def given_root_scoped_with_k(context, root_id: str, k_min: float) -> None:
    world = get_world(context)
    world.set_scoped_root(root_id)
    world.decomposer_script.setdefault("slot_k_min", {})[root_id] = k_min


@given("the ledger is set to:")
def given_ledger_is_set(context) -> None:
    world = get_world(context)
    world.set_ledger(table_rows(context.table))


@given('epsilon = {epsilon:f}')
def given_epsilon(context, epsilon: float) -> None:
    world = get_world(context)
    world.set_epsilon(epsilon)


@given(
    'a scoped root "{root_id}" with slot "{slot_key}" decomposed as {decomp_type} coupling '
    "{coupling:f} into NEC children:"
)
def given_scoped_root_with_slot(context, root_id: str, slot_key: str, decomp_type: str, coupling: float) -> None:
    world = get_world(context)
    world.set_scoped_root(root_id)
    world.set_decomposer_slot_decomposition(slot_key, decomp_type, coupling, table_rows(context.table))


@given('a scoped root "{root_id}"')
def given_scoped_root(context, root_id: str) -> None:
    world = get_world(context)
    world.set_scoped_root(root_id)


@given('slot node "{node_key}" has initial p = {p_value:f}')
def given_slot_initial_p(context, node_key: str, p_value: float) -> None:
    world = get_world(context)
    world.set_slot_initial_p(node_key, p_value)


@given('only child "{child_id}" is evaluated with p={p_value:f} and evidence_refs "{refs}"')
def given_only_child_evaluated(context, child_id: str, p_value: float, refs: str) -> None:
    world = get_world(context)
    world.set_child_evaluated(child_id, p_value, refs)


@given("the ledger is externally corrupted so that sum(named_roots) = 1.2 and H_other = -0.2")
def given_ledger_corrupted(context) -> None:
    world = get_world(context)
    world.ledger = {"corrupted": True}


@given("I ran a session and captured its audit trace")
def given_captured_audit_trace(context) -> None:
    world = get_world(context)
    world.audit_trace = [{"event_type": "PLACEHOLDER"}]


@given("the CLI adapter is configured with an application runner instance")
def given_cli_adapter_configured(context) -> None:
    world = get_world(context)
    world.decomposer_script["cli_configured"] = True


@given("the API adapter is configured with an application runner instance")
def given_api_adapter_configured(context) -> None:
    world = get_world(context)
    world.decomposer_script["api_configured"] = True


@when('I start a session for claim "{claim}"')
def when_start_session(context, claim: str) -> None:
    world = get_world(context)
    world.run_engine(f"start_session:{claim}")


@when("I run the engine until credits exhausted")
def when_run_until_credits_exhausted(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@when("I run the engine until it stops")
def when_run_until_stops(context) -> None:
    world = get_world(context)
    world.run_engine("until_stops")


@when('I run the engine for exactly {count:d} operations')
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


@when("I replay the session using only the audit trace as the source of operations and numeric outcomes")
def when_replay_session(context) -> None:
    world = get_world(context)
    world.mark_pending("Replay execution not implemented")


@when("I call the application run use case directly as a library function")
def when_call_library_use_case(context) -> None:
    world = get_world(context)
    world.mark_pending("Library run use case not implemented")


@when("the CLI adapter is invoked with args that specify claim and credits")
def when_cli_adapter_invoked(context) -> None:
    world = get_world(context)
    world.mark_pending("CLI adapter not implemented")


@when("the API endpoint is called with a JSON body specifying claim and config")
def when_api_endpoint_called(context) -> None:
    world = get_world(context)
    world.mark_pending("API adapter not implemented")


@then('the session contains root "{root_id}"')
def then_session_contains_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert root_id in world.result.get("roots", {})


@then('the ledger probabilities sum to 1.0 within {tolerance:f}')
def then_ledger_sum(context, tolerance: float) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    total = sum(world.result.get("ledger", {}).values())
    assert abs(total - 1.0) <= tolerance


@then('each named root has p_ledger = (1 - gamma) / N where N is count(named_roots)')
def then_named_root_p_ledger(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    gamma = float(world.config.get("gamma", 0.0))
    named_roots = [root_id for root_id in world.result["roots"] if root_id != "H_other"]
    count_named = len(named_roots)
    expected = (1.0 - gamma) / count_named if count_named else 0.0
    for root_id in named_roots:
        actual = world.result["ledger"].get(root_id)
        assert actual is not None
        assert abs(actual - expected) <= 1e-9


@then('H_other has p_ledger = gamma')
def then_h_other_gamma(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    gamma = float(world.config.get("gamma", 0.0))
    actual = world.result["ledger"].get("H_other")
    assert actual is not None
    assert abs(actual - gamma) <= 1e-9


@then('every root starts with k_root = 0.15')
def then_every_root_k_root(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root in world.result.get("roots", {}).values():
        assert abs(root.get("k_root", 0.0) - 0.15) <= 1e-12


@then('every named root starts with status "{status}"')
def then_named_root_status(context, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id == "H_other":
            continue
        assert root.get("status") == status


@then("the engine records a canonical_id for every root derived from normalized statement text")
def then_canonical_id_recorded(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id == "H_other":
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
        if root_id != "H_other"
    }
    canonical_b = {
        root_id: root.get("canonical_id")
        for root_id, root in world.replay_result.get("roots", {}).items()
        if root_id != "H_other"
    }
    assert canonical_a == canonical_b


@then('both "{root_a}" and "{root_b}" become status "{status}"')
def then_both_roots_status(context, root_a: str, root_b: str, status: str) -> None:
    world = get_world(context)
    world.mark_pending("scoping status check not implemented")


@then("each root has exactly the required template slots")
def then_each_root_required_slots(context) -> None:
    world = get_world(context)
    world.mark_pending("template slots check not implemented")


@then('each unassessed NEC slot has p = {p_value:f} and k = {k_value:f}')
def then_unassessed_slots_default(context, p_value: float, k_value: float) -> None:
    world = get_world(context)
    world.mark_pending("unassessed slot defaults not implemented")


@then('root "{root_id}" remains status "{status}"')
def then_root_status(context, root_id: str, status: str) -> None:
    world = get_world(context)
    world.mark_pending("root status check not implemented")


@then('root "{root_id}" has k_root <= {k_max:f}')
def then_root_k_capped(context, root_id: str, k_max: float) -> None:
    world = get_world(context)
    world.mark_pending("k_root cap check not implemented")


@then("the audit log records that UNSCOPED capping was applied")
def then_audit_unscope_capping(context) -> None:
    world = get_world(context)
    world.mark_pending("audit UNSCOPED capping check not implemented")


@then('total_credits_spent = {credits:d}')
def then_total_credits_spent(context, credits: int) -> None:
    world = get_world(context)
    world.mark_pending("credits spent check not implemented")


@then('the audit log contains exactly {count:d} operation records')
def then_audit_op_count(context, count: int) -> None:
    world = get_world(context)
    world.mark_pending("audit operation count check not implemented")


@then('each operation record includes: op_type, target_id, credits_before, credits_after')
def then_audit_op_fields(context) -> None:
    world = get_world(context)
    world.mark_pending("audit operation fields check not implemented")


@then('stop_reason is "{reason}"')
def then_stop_reason(context, reason: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert world.result.get("stop_reason") == reason


@then("no operations were executed")
def then_no_operations_executed(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert len(world.result.get("operation_log", [])) == 0


@then('credits_remaining = {credits:d}')
def then_credits_remaining(context, credits: int) -> None:
    world = get_world(context)
    world.mark_pending("credits remaining check not implemented")


@then("all named roots are SCOPED")
def then_all_named_roots_scoped(context) -> None:
    world = get_world(context)
    world.mark_pending("all roots scoped check not implemented")


@then('each named root p_ledger is unchanged from its initial value within {tolerance:f}')
def then_named_root_p_unchanged(context, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("p_ledger unchanged check not implemented")


@then('H_other p_ledger is unchanged from its initial value within {tolerance:f}')
def then_h_other_p_unchanged(context, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("H_other p_ledger unchanged check not implemented")


@then('slot "{slot_key}" has aggregated p = {p_value:f}')
def then_slot_aggregated_p(context, slot_key: str, p_value: float) -> None:
    world = get_world(context)
    world.mark_pending("slot aggregated p check not implemented")


@then("no ledger probability changed due to unassessed NEC children")
def then_no_ledger_change_unassessed(context) -> None:
    world = get_world(context)
    world.mark_pending("no ledger change check not implemented")


@then("the audit log includes a computed multiplier m_H1 = product(slot_p_values)")
def then_audit_multiplier(context) -> None:
    world = get_world(context)
    world.mark_pending("audit multiplier check not implemented")


@then("the audit log includes p_prop(H1) = p_base(H1) * m_H1")
def then_audit_p_prop(context) -> None:
    world = get_world(context)
    world.mark_pending("audit p_prop check not implemented")


@then('the audit log includes damped update with alpha = {alpha:f}')
def then_audit_damped_update(context, alpha: float) -> None:
    world = get_world(context)
    world.mark_pending("audit damped update check not implemented")


@then("H_other is set to 1 - sum(named_roots)")
def then_h_other_absorber(context) -> None:
    world = get_world(context)
    world.mark_pending("H_other absorber check not implemented")


@then("the engine enforces the Other absorber invariant")
def then_enforces_other_absorber(context) -> None:
    world = get_world(context)
    world.mark_pending("Other absorber enforcement check not implemented")


@then("all p_ledger values are in [0,1]")
def then_p_ledger_in_range(context) -> None:
    world = get_world(context)
    world.mark_pending("p_ledger range check not implemented")


@then("the audit log records which branch was taken (S<=1 or S>1)")
def then_audit_branch_recorded(context) -> None:
    world = get_world(context)
    world.mark_pending("audit branch record check not implemented")


@then('the frontier contains exactly {root_set}')
def then_frontier_contains(context, root_set: str) -> None:
    world = get_world(context)
    world.mark_pending("frontier contains check not implemented")


@then("the audit log records the leader and the frontier definition")
def then_audit_frontier(context) -> None:
    world = get_world(context)
    world.mark_pending("audit frontier check not implemented")


@then("the operation order follows canonical_id order of statements, not the provided ids")
def then_operation_order_canonical(context) -> None:
    world = get_world(context)
    world.mark_pending("operation order check not implemented")


@then("the audit log shows deterministic tie-breaking")
def then_audit_tie_breaking(context) -> None:
    world = get_world(context)
    world.mark_pending("audit tie-breaking check not implemented")


@then('the final p_ledger and k_root for each named root are identical within {tolerance:f}')
def then_final_ledger_identical(context, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("final ledger comparison not implemented")


@then('the final H_other p_ledger is identical within {tolerance:f}')
def then_final_h_other_identical(context, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("final H_other comparison not implemented")


@then("the sequence of executed operations is identical when compared by canonical target_id")
def then_operations_identical(context) -> None:
    world = get_world(context)
    world.mark_pending("operation sequence comparison not implemented")


@then('the aggregated p for slot "{slot_key}" equals {expected:f} within {tolerance:f}')
def then_soft_and_expected(context, slot_key: str, expected: float, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("soft-AND expected check not implemented")


@then("the audit log shows p_min, p_prod, c, and the computed m")
def then_audit_soft_and(context) -> None:
    world = get_world(context)
    world.mark_pending("soft-AND audit check not implemented")


@then('unassessed children "{child_a}" and "{child_b}" are treated as p=1.0 in aggregation')
def then_unassessed_children(context, child_a: str, child_b: str) -> None:
    world = get_world(context)
    world.mark_pending("unassessed children aggregation check not implemented")


@then('the aggregated slot p is <= {upper:f} and >= {lower:f}')
def then_aggregated_slot_range(context, upper: float, lower: float) -> None:
    world = get_world(context)
    world.mark_pending("aggregated slot range check not implemented")


@then('k equals {expected:f}')
def then_k_equals(context, expected: float) -> None:
    world = get_world(context)
    world.mark_pending("k equals check not implemented")


@then('k <= {expected:f}')
def then_k_leq(context, expected: float) -> None:
    world = get_world(context)
    world.mark_pending("k guardrail check not implemented")


@then("the audit log records that the guardrail cap was applied")
def then_guardrail_audit(context) -> None:
    world = get_world(context)
    world.mark_pending("guardrail audit check not implemented")


@then('the stored p for "{node_key}" equals {expected:f} within {tolerance:f}')
def then_stored_p_equals(context, node_key: str, expected: float, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("stored p check not implemented")


@then("the audit log records that conservative delta was enforced")
def then_conservative_delta_audit(context) -> None:
    world = get_world(context)
    world.mark_pending("conservative delta audit check not implemented")


@then("the audit trace contains entries for:")
def then_audit_trace_contains(context) -> None:
    world = get_world(context)
    world.mark_pending("audit trace entries check not implemented")


@then("every numeric value used in ledger updates is recorded with sufficient precision")
def then_audit_numeric_precision(context) -> None:
    world = get_world(context)
    world.mark_pending("audit numeric precision check not implemented")


@then('the replayed final p_ledger values equal the original final p_ledger values within {tolerance:f}')
def then_replay_ledger_equals(context, tolerance: float) -> None:
    world = get_world(context)
    world.mark_pending("replay ledger equality check not implemented")


@then('the replayed stop_reason equals the original stop_reason')
def then_replay_stop_reason(context) -> None:
    world = get_world(context)
    world.mark_pending("replay stop reason check not implemented")


@then("I get a SessionResult object with:")
def then_session_result_fields(context) -> None:
    world = get_world(context)
    world.mark_pending("SessionResult fields check not implemented")


@then("the CLI adapter calls exactly one application run use case")
def then_cli_calls_use_case(context) -> None:
    world = get_world(context)
    world.mark_pending("CLI adapter use case check not implemented")


@then("the CLI output is derived only from SessionResult (no domain/infrastructure leakage)")
def then_cli_output_from_session_result(context) -> None:
    world = get_world(context)
    world.mark_pending("CLI output check not implemented")


@then("the API adapter calls exactly one application run use case")
def then_api_calls_use_case(context) -> None:
    world = get_world(context)
    world.mark_pending("API adapter use case check not implemented")


@then("the API response is derived only from SessionResult")
def then_api_response_from_session_result(context) -> None:
    world = get_world(context)
    world.mark_pending("API response check not implemented")
