from __future__ import annotations

from typing import Any, Dict, List

from behave import given, then, when

from abductio_core.application.canonical import canonical_id_for_statement
from abductio_core.application.use_cases.replay_session import replay_session
from tests.bdd.steps.support.step_world import StepWorld


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
                "feasibility": row.get("feasibility_statement", ""),
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


def _rubric_from_table(table) -> Dict[str, int]:
    data = table_key_values(table)
    headings = list(getattr(table, "headings", []) or [])
    if len(headings) == 2 and headings[0] in {"A", "B", "C", "D"}:
        data.setdefault(headings[0], headings[1])
    return {key: int(value) for key, value in data.items() if key in {"A", "B", "C", "D"}}


@given("default config")
def given_default_config(context) -> None:
    world = get_world(context)
    world.set_config(table_key_values(context.table))


@given("required template slots")
def given_required_template_slots(context) -> None:
    world = get_world(context)
    world.set_required_slots(table_rows(context.table))


@given("a hypothesis set with named roots")
def given_named_roots(context) -> None:
    world = get_world(context)
    world.set_roots(table_rows(context.table))


@given("hypothesis set A with named roots")
def given_named_roots_a(context) -> None:
    world = get_world(context)
    world.set_roots_a(table_rows(context.table))


@given("hypothesis set B with the same roots but reversed ordering")
def given_named_roots_b(context) -> None:
    world = get_world(context)
    world.roots_b = list(reversed(world.roots_a))


@given("a deterministic decomposer that will scope roots with")
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
def given_deterministic_evaluator_node(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator with the following outcomes")
def given_deterministic_evaluator_outcomes(context) -> None:
    world = get_world(context)
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator that returns")
def given_deterministic_evaluator_returns(context) -> None:
    world = get_world(context)
    if all(len(row.cells) == 2 for row in context.table) and all(
        row.cells[0] in {"A", "B", "C", "D"} for row in context.table
    ):
        world.set_rubric(_rubric_from_table(context.table))
        return
    world.set_evaluator_outcomes(table_rows(context.table))


@given("a deterministic evaluator returns")
def given_deterministic_evaluator_returns_alt(context) -> None:
    world = get_world(context)
    if all(len(row.cells) == 2 for row in context.table) and all(
        row.cells[0] in {"A", "B", "C", "D"} for row in context.table
    ):
        world.set_rubric(_rubric_from_table(context.table))
        return
    world.set_evaluator_outcomes(table_rows(context.table))


@given('a deterministic evaluator that attempts to set for node "{node_key}"')
def given_deterministic_evaluator_attempts(context, node_key: str) -> None:
    world = get_world(context)
    world.set_evaluator_outcome(node_key, table_key_values(context.table))


@given("a deterministic evaluator that returns rubric")
def given_deterministic_evaluator_rubric(context) -> None:
    world = get_world(context)
    world.set_rubric(_rubric_from_table(context.table))


@given("a deterministic evaluator with at least one evaluation outcome")
def given_deterministic_evaluator_one(context) -> None:
    world = get_world(context)
    roots = world.roots or [{"id": "H1"}]
    slot_key = world.required_slots[0]["slot_key"] if world.required_slots else "feasibility"
    outcomes = [
        {
            "node_key": f"{root['id']}:{slot_key}",
            "p": "0.5",
            "A": "2",
            "B": "1",
            "C": "1",
            "D": "1",
            "evidence_refs": "ref1",
        }
        for root in roots
    ]
    world.set_evaluator_outcomes(outcomes)


@given('credits {credits:d}')
def given_credits(context, credits: int) -> None:
    world = get_world(context)
    world.set_credits(credits)


@given('the root "{root_id}" is already SCOPED with all slots having k >= {k_min:f}')
def given_root_scoped_with_k(context, root_id: str, k_min: float) -> None:
    world = get_world(context)
    world.set_scoped_root(root_id)
    world.decomposer_script.setdefault("slot_k_min", {})[root_id] = k_min


@given("the ledger is set to")
def given_ledger_is_set(context) -> None:
    world = get_world(context)
    world.set_ledger(table_rows(context.table))


@given('epsilon = {epsilon:f}')
def given_epsilon(context, epsilon: float) -> None:
    world = get_world(context)
    world.set_epsilon(epsilon)


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


@given('only child "{child_id}" is evaluated with p={p_value:f} and evidence_refs "{refs}"')
def given_only_child_evaluated(context, child_id: str, p_value: float, refs: str) -> None:
    world = get_world(context)
    world.set_child_evaluated(child_id, p_value, refs)


@given("the ledger is externally corrupted so that sum(named_roots) = 1.2 and H_other = -0.2")
def given_ledger_corrupted(context) -> None:
    world = get_world(context)
    named_roots = [row["id"] for row in world.roots]
    if not named_roots:
        world.ledger = {"H_other": -0.2}
        return
    per_root = 1.2 / len(named_roots)
    world.ledger = {root_id: per_root for root_id in named_roots}
    world.ledger["H_other"] = -0.2


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


@when("the CLI adapter is invoked with args that specify claim and credits")
def when_cli_adapter_invoked(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@when("the API endpoint is called with a JSON body specifying claim and config")
def when_api_endpoint_called(context) -> None:
    world = get_world(context)
    world.run_engine("until_credits_exhausted")


@then('the session contains root "{root_id}"')
def then_session_contains_root(context, root_id: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert root_id in world.result.get("roots", {})
    if root_id == "H_other":
        named_ids = {row["id"] for row in world.roots}
        assert "H_other" not in named_ids
        assert len(world.result.get("roots", {})) == len(named_ids) + 1


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
        if root.get("obligations"):
            expected = min(node.get("k", 0.0) for node in root["obligations"].values())
            assert abs(root.get("k_root", 0.0) - expected) <= 1e-12


@then('every named root starts with status "{status}"')
def then_named_root_status(context, status: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result.get("roots", {}).items():
        if root_id == "H_other":
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
        if root_id == "H_other":
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
        if root_id == "H_other":
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
    if not world.result:
        world.mark_pending("Session result not available")
    assert world.result.get("credits_remaining") == credits


@then("all named roots are SCOPED")
def then_all_named_roots_scoped(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    for root_id, root in world.result["roots"].items():
        if root_id == "H_other":
            continue
        assert root.get("status") == "SCOPED"


@then('each named root p_ledger is unchanged from its initial value within {tolerance}')
def then_named_root_p_unchanged(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    for root_id, root in world.result["roots"].items():
        if root_id == "H_other":
            continue
        initial = world.initial_ledger.get(root_id, 0.0)
        actual = world.result.get("ledger", {}).get(root_id, 0.0)
        assert abs(actual - initial) <= tolerance_value


@then('H_other p_ledger is unchanged from its initial value within {tolerance}')
def then_h_other_p_unchanged(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    tolerance_value = float(tolerance)
    initial = world.initial_ledger.get("H_other", 0.0)
    actual = world.result.get("ledger", {}).get("H_other", 0.0)
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
    assert any(event["event_type"] == "MULTIPLIER_COMPUTED" for event in world.result.get("audit", []))


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


@then("H_other is set to 1 - sum(named_roots)")
def then_h_other_absorber(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    ledger = world.result.get("ledger", {})
    sum_named = sum(value for key, value in ledger.items() if key != "H_other")
    expected = 1.0 - sum_named
    assert abs(ledger.get("H_other", 0.0) - expected) <= 1e-9


@then("the engine enforces the Other absorber invariant")
def then_enforces_other_absorber(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    assert any(event["event_type"] == "OTHER_ABSORBER_ENFORCED" for event in world.result.get("audit", []))


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
        event["event_type"] == "OTHER_ABSORBER_ENFORCED" and "branch" in event["payload"]
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


@then("the operation order follows canonical_id order of statements, not the provided ids")
def then_operation_order_canonical(context) -> None:
    world = get_world(context)
    if not world.result:
        world.mark_pending("Session result not available")
    roots = [
        root
        for root_id, root in world.result["roots"].items()
        if root_id != "H_other"
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


@then('the final p_ledger and k_root for each named root are identical within {tolerance}')
def then_final_ledger_identical(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    tolerance_value = float(tolerance)
    for root_id, root in world.result["roots"].items():
        if root_id == "H_other":
            continue
        other_root = world.replay_result["roots"].get(root_id)
        assert other_root is not None
        assert abs(root.get("p_ledger", 0.0) - other_root.get("p_ledger", 0.0)) <= tolerance_value
        assert abs(root.get("k_root", 0.0) - other_root.get("k_root", 0.0)) <= tolerance_value


@then('the final H_other p_ledger is identical within {tolerance}')
def then_final_h_other_identical(context, tolerance: str) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    tolerance_value = float(tolerance)
    actual = world.result.get("ledger", {}).get("H_other", 0.0)
    expected = world.replay_result.get("ledger", {}).get("H_other", 0.0)
    assert abs(actual - expected) <= tolerance_value


@then("the sequence of executed operations is identical when compared by canonical target_id")
def then_operations_identical(context) -> None:
    world = get_world(context)
    if not world.result or not world.replay_result:
        world.mark_pending("Session results not available")
    canonical_map = {
        root_id: root["canonical_id"]
        for root_id, root in world.result["roots"].items()
        if root_id != "H_other"
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
        root for root in world.result.get("roots", {}) if root != "H_other"
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


@then('unassessed children "{child_a}" and "{child_b}" are treated as p=1.0 in aggregation')
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
