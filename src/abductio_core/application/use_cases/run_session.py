from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from abductio_core.application.dto import SessionRequest
from abductio_core.application.result import SessionResult, StopReason
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.canonical import canonical_id_for_statement
from abductio_core.domain.invariants import H_OTHER_ID, enforce_absorber
from abductio_core.domain.model import HypothesisSet, Node, RootHypothesis


def _init_hypothesis_set(request: SessionRequest) -> HypothesisSet:
    roots: Dict[str, RootHypothesis] = {}
    ledger: Dict[str, float] = {}
    named_roots = request.roots
    count_named = len(named_roots)
    gamma = request.config.gamma
    base_p = (1.0 - gamma) / count_named if count_named else 0.0

    for root in named_roots:
        canonical_id = canonical_id_for_statement(root.statement)
        roots[root.root_id] = RootHypothesis(
            root_id=root.root_id,
            statement=root.statement,
            exclusion_clause=root.exclusion_clause,
            canonical_id=canonical_id,
        )
        ledger[root.root_id] = base_p

    roots[H_OTHER_ID] = RootHypothesis(
        root_id=H_OTHER_ID,
        statement="Other",
        exclusion_clause="Not explained by any named root",
        canonical_id=canonical_id_for_statement("Other"),
    )
    ledger[H_OTHER_ID] = gamma if count_named else 1.0

    if request.initial_ledger:
        ledger.update(request.initial_ledger)

    return HypothesisSet(roots=roots, ledger=ledger)


def _required_slot_keys(request: SessionRequest) -> list[str]:
    required_slots = request.required_slots or []
    return [row["slot_key"] for row in required_slots if "slot_key" in row]


def _required_slot_roles(request: SessionRequest) -> Dict[str, str]:
    required_slots = request.required_slots or []
    return {row["slot_key"]: row.get("role", "NEC") for row in required_slots if "slot_key" in row}


def _slots_missing(root: RootHypothesis, required_slot_keys: list[str]) -> bool:
    return any(slot_key not in root.obligations for slot_key in required_slot_keys)


def _node_statement_map(decomposition: Dict[str, str]) -> Dict[str, str]:
    return {
        "feasibility": decomposition.get("feasibility_statement", ""),
        "availability": decomposition.get("availability_statement", ""),
        "fit_to_key_features": decomposition.get("fit_statement", ""),
        "defeater_resistance": decomposition.get("defeater_statement", ""),
    }


def _decompose_root(
    root: RootHypothesis,
    required_slot_keys: list[str],
    required_slot_roles: Dict[str, str],
    decomposition: Dict[str, str],
    deps: RunSessionDeps,
    slot_k_min: Optional[float] = None,
    slot_initial_p: Optional[Dict[str, float]] = None,
) -> None:
    ok = bool(decomposition) and decomposition.get("ok", True)
    if not ok:
        root.k_root = min(root.k_root, 0.40)
        deps.audit_sink.append(
            AuditEvent(
                event_type="UNSCOPED_CAPPED",
                payload={"root_id": root.root_id, "k_root": root.k_root},
            )
        )
        return

    statement_map = _node_statement_map(decomposition)
    for slot_key in required_slot_keys:
        if slot_key in root.obligations:
            continue
        node_key = f"{root.root_id}:{slot_key}"
        statement = statement_map.get(slot_key) or ""
        role = required_slot_roles.get(slot_key, "NEC")
        initial_p = 1.0
        if slot_initial_p and node_key in slot_initial_p:
            initial_p = float(slot_initial_p[node_key])
        node_k = slot_k_min if slot_k_min is not None else 0.15
        root.obligations[slot_key] = Node(
            node_key=node_key,
            statement=statement,
            role=role,
            p=initial_p,
            k=node_k,
        )
    root.status = "SCOPED"
    if root.obligations:
        root.k_root = min(node.k for node in root.obligations.values())


def _slot_alias(slot_key: str) -> str:
    if slot_key == "fit_to_key_features":
        return "fit"
    return slot_key


def _apply_slot_decomposition(
    root: RootHypothesis,
    slot_key: str,
    decomposition: Dict[str, object],
    child_nodes: Dict[str, Node],
) -> None:
    if not decomposition or not decomposition.get("children"):
        return
    node = root.obligations.get(slot_key)
    if not node:
        return
    node.decomp_type = decomposition.get("type")
    node.coupling = decomposition.get("coupling")
    node.children = []
    alias = _slot_alias(slot_key)
    for child in decomposition.get("children", []):
        child_id = child.get("child_id") or child.get("id")
        if not child_id:
            continue
        node_key = f"{root.root_id}:{alias}:{child_id}"
        child_nodes[node_key] = Node(
            node_key=node_key,
            statement=child.get("statement", ""),
            role=child.get("role", "NEC"),
            p=1.0,
            k=0.15,
        )
        node.children.append(node_key)


def _compute_frontier(
    roots: Iterable[RootHypothesis],
    ledger: Dict[str, float],
    epsilon: float,
) -> Tuple[Optional[str], List[RootHypothesis]]:
    named_roots = list(roots)
    if not named_roots:
        return None, []
    leader = max(named_roots, key=lambda root: ledger.get(root.root_id, 0.0))
    leader_p = ledger.get(leader.root_id, 0.0)
    frontier = [
        root
        for root in named_roots
        if ledger.get(root.root_id, 0.0) >= leader_p - epsilon
    ]
    frontier_sorted = sorted(frontier, key=lambda root: root.canonical_id)
    return leader.root_id, frontier_sorted


def _derive_k_from_rubric(rubric: Dict[str, int]) -> Tuple[float, bool]:
    total = sum(rubric.values())
    mapping = {
        0: 0.15,
        1: 0.25,
        2: 0.35,
        3: 0.45,
        4: 0.55,
        5: 0.65,
        6: 0.75,
        7: 0.85,
        8: 0.90,
    }
    base_k = mapping.get(total, 0.15)
    guardrail = any(value == 0 for value in rubric.values()) if rubric else False
    if guardrail and base_k > 0.55:
        return 0.55, True
    return base_k, guardrail


def _aggregate_soft_and(
    slot_node: Node,
    child_nodes: Dict[str, Node],
) -> Tuple[float, Dict[str, float]]:
    children = [child_nodes[child_key] for child_key in slot_node.children if child_key in child_nodes]
    if not children:
        return slot_node.p, {"p_min": slot_node.p, "p_prod": slot_node.p, "c": slot_node.coupling or 0.0}
    p_values = [child.p for child in children]
    p_min = min(p_values)
    p_prod = 1.0
    for value in p_values:
        p_prod *= value
    coupling = slot_node.coupling or 0.0
    aggregated = coupling * p_min + (1.0 - coupling) * p_prod
    return aggregated, {"p_min": p_min, "p_prod": p_prod, "c": coupling}


def run_session(request: SessionRequest, deps: RunSessionDeps) -> SessionResult:
    hypothesis_set = _init_hypothesis_set(request)
    named_root_ids = [root_id for root_id in hypothesis_set.roots if root_id != H_OTHER_ID]
    sum_named = sum(hypothesis_set.ledger.get(root_id, 0.0) for root_id in named_root_ids)
    branch = "S<=1" if sum_named <= 1.0 else "S>1"
    enforce_absorber(hypothesis_set.ledger, named_root_ids)
    deps.audit_sink.append(
        AuditEvent(
            event_type="OTHER_ABSORBER_ENFORCED",
            payload={"branch": branch, "sum_named": sum_named},
        )
    )
    deps.audit_sink.append(
        AuditEvent(
            event_type="INVARIANT_SUM_TO_ONE_CHECK",
            payload={"total": sum(hypothesis_set.ledger.values())},
        )
    )

    required_slot_keys = _required_slot_keys(request)
    required_slot_roles = _required_slot_roles(request)
    operation_log = []
    credits_remaining = request.credits
    total_credits_spent = 0
    child_nodes: Dict[str, Node] = {}
    frontier_index = 0
    frontier_signature: Optional[Tuple[str, ...]] = None
    run_mode = request.run_mode or "until_credits_exhausted"
    operation_limit = request.run_count if run_mode in {"operations", "evaluation", "evaluations_children"} else None
    pre_scoped = request.pre_scoped_roots or []
    slot_k_min = request.slot_k_min or {}
    slot_initial_p = request.slot_initial_p or {}

    for root_id in pre_scoped:
        root = hypothesis_set.roots.get(root_id)
        if not root:
            continue
        decomposition = deps.decomposer.decompose(root_id)
        _decompose_root(
            root,
            required_slot_keys,
            required_slot_roles,
            decomposition,
            deps,
            slot_k_min=slot_k_min.get(root_id),
            slot_initial_p=slot_initial_p,
        )
        for slot_key, node in root.obligations.items():
            slot_decomp = deps.decomposer.decompose(f"{root.root_id}:{slot_key}")
            _apply_slot_decomposition(root, slot_key, slot_decomp, child_nodes)
            if node.children:
                aggregated, _ = _aggregate_soft_and(node, child_nodes)
                node.p = aggregated

    def record_operation(op_type: str, target_id: str, credits_before: int) -> None:
        operation_log.append(
            {
                "op_type": op_type,
                "target_id": target_id,
                "credits_before": credits_before,
                "credits_after": credits_remaining,
            }
        )
        deps.audit_sink.append(
            AuditEvent(
                event_type="OP_EXECUTED",
                payload={
                    "op_type": op_type,
                    "target_id": target_id,
                    "credits_before": credits_before,
                    "credits_after": credits_remaining,
                },
            )
        )

    def apply_ledger_update(root: RootHypothesis) -> None:
        slot_p_values = [node.p for node in root.obligations.values()] or [1.0]
        multiplier = 1.0
        for value in slot_p_values:
            multiplier *= value
        deps.audit_sink.append(
            AuditEvent(
                event_type="MULTIPLIER_COMPUTED",
                payload={"root_id": root.root_id, "slot_p_values": slot_p_values, "m": multiplier},
            )
        )
        p_base = hypothesis_set.ledger.get(root.root_id, 0.0)
        p_prop = p_base * multiplier
        deps.audit_sink.append(
            AuditEvent(
                event_type="P_PROP_COMPUTED",
                payload={"root_id": root.root_id, "p_base": p_base, "p_prop": p_prop},
            )
        )
        alpha = request.config.alpha
        p_new = p_base + alpha * (p_prop - p_base)
        hypothesis_set.ledger[root.root_id] = p_new
        deps.audit_sink.append(
            AuditEvent(
                event_type="DAMPING_APPLIED",
                payload={"root_id": root.root_id, "alpha": alpha, "p_base": p_base, "p_new": p_new},
            )
        )
        sum_named_local = sum(
            hypothesis_set.ledger.get(root_id, 0.0)
            for root_id in hypothesis_set.roots
            if root_id != H_OTHER_ID
        )
        branch_local = "S<=1" if sum_named_local <= 1.0 else "S>1"
        enforce_absorber(hypothesis_set.ledger, named_root_ids)
        deps.audit_sink.append(
            AuditEvent(
                event_type="OTHER_ABSORBER_ENFORCED",
                payload={"branch": branch_local, "sum_named": sum_named_local},
            )
        )
        deps.audit_sink.append(
            AuditEvent(
                event_type="INVARIANT_SUM_TO_ONE_CHECK",
                payload={"total": sum(hypothesis_set.ledger.values())},
            )
        )

    def evaluate_node(root: RootHypothesis, node_key: str) -> None:
        node = None
        if node_key in child_nodes:
            node = child_nodes[node_key]
        else:
            for slot in root.obligations.values():
                if slot.node_key == node_key:
                    node = slot
                    break
        if not node:
            return
        outcome = deps.evaluator.evaluate(node_key) or {}
        if not outcome:
            return
        previous_p = node.p
        proposed_p = float(outcome.get("p", previous_p))
        evidence_refs = outcome.get("evidence_refs", "")
        refs = [ref for ref in str(evidence_refs).split(",") if ref] if evidence_refs != "(empty)" else []
        if not refs:
            delta = max(min(proposed_p - previous_p, 0.05), -0.05)
            proposed_p = previous_p + delta
            deps.audit_sink.append(
                AuditEvent(
                    event_type="CONSERVATIVE_DELTA_ENFORCED",
                    payload={"node_key": node_key, "p_before": previous_p, "p_after": proposed_p},
                )
            )
        node.p = proposed_p
        rubric = {
            key: int(outcome[key])
            for key in ("A", "B", "C", "D")
            if key in outcome and str(outcome[key]).isdigit()
        }
        if rubric:
            node.k, guardrail = _derive_k_from_rubric(rubric)
            if guardrail:
                deps.audit_sink.append(
                    AuditEvent(
                        event_type="K_GUARDRAIL_APPLIED",
                        payload={"node_key": node_key, "k": node.k},
                    )
                )
        if node_key in child_nodes:
            for slot_key, slot_node in root.obligations.items():
                if node_key in slot_node.children and slot_node.decomp_type == "AND":
                    aggregated, details = _aggregate_soft_and(slot_node, child_nodes)
                    slot_node.p = aggregated
                    deps.audit_sink.append(
                        AuditEvent(
                            event_type="SOFT_AND_COMPUTED",
                            payload={
                                "slot_key": slot_key,
                                "p_min": details["p_min"],
                                "p_prod": details["p_prod"],
                                "c": details["c"],
                                "m": aggregated,
                            },
                        )
                    )
        if root.obligations:
            root.k_root = min(node.k for node in root.obligations.values())
        apply_ledger_update(root)

    def select_slot_for_evaluation(root: RootHypothesis) -> Optional[str]:
        if not root.obligations:
            return None
        order_map = {slot_key: index for index, slot_key in enumerate(required_slot_keys)}
        ordered = sorted(
            root.obligations.items(),
            key=lambda item: (item[1].k, order_map.get(item[0], len(order_map)), item[1].node_key),
        )
        return ordered[0][1].node_key

    def select_slot_for_decomposition(root: RootHypothesis) -> Optional[str]:
        for slot_key, node in root.obligations.items():
            if node.children:
                continue
            slot_decomp = deps.decomposer.decompose(f"{root.root_id}:{slot_key}")
            if slot_decomp.get("children"):
                _apply_slot_decomposition(root, slot_key, slot_decomp, child_nodes)
                if node.children:
                    aggregated, details = _aggregate_soft_and(node, child_nodes)
                    node.p = aggregated
                    deps.audit_sink.append(
                        AuditEvent(
                            event_type="SOFT_AND_COMPUTED",
                            payload={
                                "slot_key": slot_key,
                                "p_min": details["p_min"],
                                "p_prod": details["p_prod"],
                                "c": details["c"],
                                "m": aggregated,
                            },
                        )
                    )
                return slot_key
        return None

    def slot_needs_decomposition(root: RootHypothesis) -> bool:
        for slot_key, node in root.obligations.items():
            if node.children:
                continue
            slot_decomp = deps.decomposer.decompose(f"{root.root_id}:{slot_key}")
            if slot_decomp.get("children"):
                return True
        return False

    def maybe_stop_for_frontier() -> Optional[StopReason]:
        leader_id, frontier = _compute_frontier(
            [root for root_id, root in hypothesis_set.roots.items() if root_id != H_OTHER_ID],
            hypothesis_set.ledger,
            request.config.epsilon,
        )
        if leader_id is not None:
            deps.audit_sink.append(
                AuditEvent(
                    event_type="FRONTIER_DEFINED",
                    payload={"leader_id": leader_id, "frontier": [root.root_id for root in frontier]},
                )
            )
        if not frontier:
            return None
        if all(root.status == "SCOPED" and root.k_root >= request.config.tau for root in frontier):
            return StopReason.FRONTIER_CONFIDENT
        return None

    if run_mode == "start_only":
        stop_reason = StopReason.CREDITS_EXHAUSTED if credits_remaining == 0 else None
    else:
        stop_reason = None
        while credits_remaining > 0:
            if run_mode in {"until_stops", "operations"}:
                stop_reason = maybe_stop_for_frontier()
                if stop_reason:
                    break
            if operation_limit is not None and total_credits_spent >= operation_limit:
                break

            leader_id, frontier = _compute_frontier(
                [root for root_id, root in hypothesis_set.roots.items() if root_id != H_OTHER_ID],
                hypothesis_set.ledger,
                request.config.epsilon,
            )
            if leader_id is not None:
                deps.audit_sink.append(
                    AuditEvent(
                        event_type="FRONTIER_DEFINED",
                        payload={"leader_id": leader_id, "frontier": [root.root_id for root in frontier]},
                    )
                )
            if not frontier:
                break
            signature = tuple(root.root_id for root in frontier)
            if signature != frontier_signature:
                frontier_signature = signature
                frontier_index = 0
                if len(frontier) > 1:
                    deps.audit_sink.append(
                        AuditEvent(
                            event_type="TIE_BREAKER_APPLIED",
                            payload={"ordered_frontier": list(signature)},
                        )
                    )
            target_root = frontier[frontier_index % len(frontier)]
            frontier_index += 1
            credits_before = credits_remaining
            node_key: Optional[str] = None

            op_type = "DECOMPOSE"
            if run_mode in {"evaluation", "evaluations_children"}:
                op_type = "EVALUATE"
            elif target_root.status == "UNSCOPED" or _slots_missing(target_root, required_slot_keys):
                op_type = "DECOMPOSE"
            elif slot_needs_decomposition(target_root):
                op_type = "DECOMPOSE"
            else:
                op_type = "EVALUATE"

            if op_type == "DECOMPOSE":
                if target_root.status == "UNSCOPED" or _slots_missing(target_root, required_slot_keys):
                    decomposition = deps.decomposer.decompose(target_root.root_id)
                    _decompose_root(
                        target_root,
                        required_slot_keys,
                        required_slot_roles,
                        decomposition,
                        deps,
                        slot_k_min=slot_k_min.get(target_root.root_id),
                        slot_initial_p=slot_initial_p,
                    )
                else:
                    select_slot_for_decomposition(target_root)
            else:
                if run_mode == "evaluations_children":
                    for slot_key, slot_node in target_root.obligations.items():
                        if slot_node.children:
                            children = sorted(slot_node.children)
                            for child_key in children:
                                if operation_limit is not None and total_credits_spent >= operation_limit:
                                    break
                                evaluate_node(target_root, child_key)
                                credits_remaining -= 1
                                total_credits_spent += 1
                                target_root.credits_spent += 1
                                record_operation(op_type, child_key, credits_before)
                                credits_before = credits_remaining
                            break
                    continue
                node_key = request.run_target if run_mode == "evaluation" and request.run_target else None
                if not node_key:
                    node_key = select_slot_for_evaluation(target_root)
                if node_key:
                    evaluate_node(target_root, node_key)
            credits_remaining -= 1
            total_credits_spent += 1
            target_root.credits_spent += 1
            op_target_id = target_root.root_id if op_type == "DECOMPOSE" else (node_key or target_root.root_id)
            record_operation(op_type, op_target_id, credits_before)

        if stop_reason is None and credits_remaining == 0:
            stop_reason = StopReason.CREDITS_EXHAUSTED

    deps.audit_sink.append(
        AuditEvent(
            event_type="STOP_REASON_RECORDED",
            payload={"stop_reason": stop_reason.value if stop_reason else None},
        )
    )

    roots_view = {
        root_id: {
            "id": root.root_id,
            "statement": root.statement,
            "exclusion_clause": root.exclusion_clause,
            "canonical_id": root.canonical_id,
            "status": root.status,
            "k_root": root.k_root,
            "p_ledger": hypothesis_set.ledger.get(root_id, 0.0),
            "credits_spent": root.credits_spent,
            "obligations": {
                slot_key: {
                    "node_key": node.node_key,
                    "statement": node.statement,
                    "role": node.role,
                    "p": node.p,
                    "k": node.k,
                    "children": list(node.children),
                    "decomp_type": node.decomp_type,
                    "coupling": node.coupling,
                }
                for slot_key, node in root.obligations.items()
            },
        }
        for root_id, root in hypothesis_set.roots.items()
    }

    return SessionResult(
        roots=roots_view,
        ledger=hypothesis_set.ledger,
        audit=[{"event_type": event.event_type, "payload": event.payload} for event in deps.audit_sink.events],
        stop_reason=stop_reason,
        credits_remaining=credits_remaining,
        total_credits_spent=total_credits_spent,
        operation_log=operation_log,
    )
