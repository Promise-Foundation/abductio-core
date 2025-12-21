from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from abductio_core.application.dto import SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.result import SessionResult, StopReason
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.canonical import canonical_id_for_statement
from abductio_core.domain.invariants import H_OTHER_ID, enforce_absorber
from abductio_core.domain.model import HypothesisSet, Node, RootHypothesis


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def _validate_request(request: SessionRequest) -> None:
    if request.credits < 0:
        raise ValueError("credits must be non-negative")
    for attr in ("tau", "epsilon", "gamma", "alpha"):
        value = getattr(request.config, attr)
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{attr} must be within [0,1]")
    for root in request.roots:
        if not root.root_id:
            raise ValueError("root_id is required")
        if not root.statement:
            raise ValueError("root statement is required")
    required_slots = request.required_slots or []
    for row in required_slots:
        if "slot_key" not in row or not row.get("slot_key"):
            raise ValueError("required slot_key is missing")


def _required_slot_keys(request: SessionRequest) -> List[str]:
    required_slots = request.required_slots
    if not required_slots:
        return ["feasibility"]
    return [row["slot_key"] for row in required_slots if "slot_key" in row]


def _required_slot_roles(request: SessionRequest) -> Dict[str, str]:
    required_slots = request.required_slots
    if not required_slots:
        return {"feasibility": "NEC"}
    return {row["slot_key"]: row.get("role", "NEC") for row in required_slots if "slot_key" in row}


def _node_statement_map(decomposition: Dict[str, str]) -> Dict[str, str]:
    return {
        "feasibility": decomposition.get("feasibility_statement", ""),
        "availability": decomposition.get("availability_statement", ""),
        "fit_to_key_features": decomposition.get("fit_statement", ""),
        "defeater_resistance": decomposition.get("defeater_statement", ""),
    }


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
        status="OTHER",
    )
    ledger[H_OTHER_ID] = gamma if count_named else 1.0

    if request.initial_ledger:
        ledger.update(request.initial_ledger)

    return HypothesisSet(roots=roots, ledger=ledger)


def _compute_frontier(
    roots: Iterable[RootHypothesis],
    ledger: Dict[str, float],
    epsilon: float,
) -> Tuple[Optional[str], List[RootHypothesis]]:
    named_roots = list(roots)
    if not named_roots:
        return None, []
    ordered = sorted(named_roots, key=lambda r: (-ledger.get(r.root_id, 0.0), r.canonical_id))
    leader = ordered[0]
    leader_p = ledger.get(leader.root_id, 0.0)
    frontier = [r for r in ordered if ledger.get(r.root_id, 0.0) >= leader_p - epsilon]
    return leader.root_id, frontier


def _derive_k_from_rubric(rubric: Dict[str, int]) -> Tuple[float, bool]:
    total = sum(rubric.values())
    if total <= 1:
        base_k = 0.15
    elif total <= 3:
        base_k = 0.35
    elif total <= 5:
        base_k = 0.55
    elif total <= 7:
        base_k = 0.75
    else:
        base_k = 0.90
    guardrail = any(value == 0 for value in rubric.values()) if rubric else False
    if guardrail and base_k > 0.55:
        return 0.55, True
    return base_k, guardrail


def _aggregate_soft_and(node: Node, nodes: Dict[str, Node]) -> Tuple[float, Dict[str, float]]:
    children = [nodes[k] for k in node.children if k in nodes]
    assessed = [c for c in children if c.assessed]
    if not assessed:
        return 1.0, {"p_min": 1.0, "p_prod": 1.0, "c": float(node.coupling or 0.0)}
    p_values = [c.p for c in assessed]
    p_min = min(p_values)
    p_prod = 1.0
    for v in p_values:
        p_prod *= v
    c = float(node.coupling or 0.0)
    m = c * p_min + (1.0 - c) * p_prod
    return m, {"p_min": p_min, "p_prod": p_prod, "c": c}


def _apply_node_decomposition(
    deps: RunSessionDeps,
    node_key: str,
    decomposition: Dict[str, object],
    nodes: Dict[str, Node],
) -> bool:
    node = nodes.get(node_key)
    if not node:
        return False
    if not decomposition or not decomposition.get("children"):
        if node.decomp_type is None:
            node.decomp_type = "NONE"
            deps.audit_sink.append(
                AuditEvent(
                    event_type="NODE_REFINED_REQUIREMENTS",
                    payload={
                        "node_key": node_key,
                        "type": node.decomp_type,
                        "coupling": node.coupling,
                        "children": [],
                    },
                )
            )
        return False

    node.decomp_type = str(decomposition.get("type") or "")
    node.coupling = decomposition.get("coupling")
    node.children = []

    for child in decomposition.get("children", []):
        if not isinstance(child, dict):
            continue
        child_id = child.get("child_id") or child.get("id")
        if not child_id:
            continue
        child_node_key = f"{node_key}:{child_id}"
        nodes[child_node_key] = Node(
            node_key=child_node_key,
            statement=str(child.get("statement", "")),
            role=str(child.get("role", "NEC")),
            p=1.0,
            k=0.15,
            assessed=False,
        )
        node.children.append(child_node_key)

    node.children.sort()
    deps.audit_sink.append(
        AuditEvent(
            event_type="NODE_REFINED_REQUIREMENTS",
            payload={
                "node_key": node_key,
                "type": node.decomp_type,
                "coupling": node.coupling,
                "children": list(node.children),
            },
        )
    )
    return True


def _decompose_root(
    deps: RunSessionDeps,
    root: RootHypothesis,
    required_slot_keys: List[str],
    required_slot_roles: Dict[str, str],
    decomposition: Dict[str, str],
    slot_k_min: Optional[float],
    slot_initial_p: Dict[str, float],
    nodes: Dict[str, Node],
) -> None:
    ok = bool(decomposition) and decomposition.get("ok", True)
    if not ok:
        root.k_root = min(root.k_root, 0.40)
        deps.audit_sink.append(AuditEvent("UNSCOPED_CAPPED", {"root_id": root.root_id, "k_root": root.k_root}))
        return

    statement_map = _node_statement_map(decomposition)
    for slot_key in required_slot_keys:
        if slot_key in root.obligations:
            continue
        node_key = f"{root.root_id}:{slot_key}"
        statement = statement_map.get(slot_key) or ""
        role = required_slot_roles.get(slot_key, "NEC")
        initial_p = float(slot_initial_p.get(node_key, 1.0))
        node_k = float(slot_k_min) if slot_k_min is not None else 0.15
        nodes[node_key] = Node(
            node_key=node_key,
            statement=statement,
            role=role,
            p=_clamp_probability(initial_p),
            k=node_k,
            assessed=False,
        )
        root.obligations[slot_key] = node_key

    root.status = "SCOPED"
    if root.obligations:
        slot_nodes = [nodes[k] for k in root.obligations.values() if k in nodes]
        if slot_nodes:
            root.k_root = min(n.k for n in slot_nodes)

    deps.audit_sink.append(
        AuditEvent(
            event_type="ROOT_SCOPED",
            payload={"root_id": root.root_id, "slots": list(root.obligations.keys())},
        )
    )


def _slot_order_map(required_slot_keys: List[str]) -> Dict[str, int]:
    return {k: i for i, k in enumerate(required_slot_keys)}


def _sorted_children(node: Node, nodes: Dict[str, Node]) -> List[str]:
    return sorted([ck for ck in node.children if ck in nodes])


def _flatten_subtree(node: Node, nodes: Dict[str, Node]) -> List[str]:
    ordered: List[str] = []
    for child_key in _sorted_children(node, nodes):
        ordered.append(child_key)
        child = nodes.get(child_key)
        if child:
            ordered.extend(_flatten_subtree(child, nodes))
    return ordered


def _select_slot_lowest_k(
    root: RootHypothesis,
    required_slot_keys: List[str],
    nodes: Dict[str, Node],
    tau: float,
) -> Optional[str]:
    order = _slot_order_map(required_slot_keys)
    candidates = []
    for slot_key in required_slot_keys:
        node_key = root.obligations.get(slot_key)
        if not node_key:
            continue
        node = nodes.get(node_key)
        if not node:
            continue
        candidates.append((node.k, order.get(slot_key, 10_000), slot_key))
    if not candidates:
        return None
    _, _, slot_key = sorted(candidates)[0]
    return slot_key


def _select_child_to_evaluate(node: Node, nodes: Dict[str, Node]) -> Optional[str]:
    if not node.children:
        return None
    candidates = []
    for ck in node.children:
        cn = nodes.get(ck)
        if not cn:
            continue
        candidates.append((cn.assessed, cn.k, cn.node_key))
    if not candidates:
        return None
    candidates.sort()
    assessed, _, node_key = candidates[0]
    if assessed:
        return None
    return node_key


def _node_needs_decomposition(node: Node, tau: float, credits_left: int) -> bool:
    return node.decomp_type is None and not node.children and float(node.k) < float(tau) and credits_left > 1


def _select_decompose_in_subtree(
    node: Node,
    nodes: Dict[str, Node],
    tau: float,
    credits_left: int,
) -> Optional[str]:
    for child_key in _sorted_children(node, nodes):
        child = nodes.get(child_key)
        if not child:
            continue
        if _node_needs_decomposition(child, tau, credits_left):
            return child.node_key
        nested = _select_decompose_in_subtree(child, nodes, tau, credits_left)
        if nested:
            return nested
    return None


def _select_unassessed_in_subtree(node: Node, nodes: Dict[str, Node]) -> Optional[str]:
    for child_key in _sorted_children(node, nodes):
        child = nodes.get(child_key)
        if not child:
            continue
        if not child.assessed:
            return child.node_key
        nested = _select_unassessed_in_subtree(child, nodes)
        if nested:
            return nested
    return None


def _select_child_for_evaluation(
    root: RootHypothesis, required_slot_keys: List[str], nodes: Dict[str, Node]
) -> Optional[str]:
    if not required_slot_keys:
        return None
    slot_order = _slot_order_map(required_slot_keys)
    slots_with_children = [
        (slot_order.get(k, 10_000), k)
        for k in required_slot_keys
        if k in root.obligations and nodes.get(root.obligations[k]) and nodes[root.obligations[k]].children
    ]
    for _, slot_key in sorted(slots_with_children):
        slot_node = nodes[root.obligations[slot_key]]
        child_key = _select_unassessed_in_subtree(slot_node, nodes)
        if child_key:
            return child_key
    return None

def _select_slot_for_evaluation(root: RootHypothesis, required_slot_keys: List[str], nodes: Dict[str, Node]) -> Optional[str]:
    if not required_slot_keys:
        return None
    available = [k for k in required_slot_keys if k in root.obligations]
    if not available:
        return None
    slot_key = _select_slot_lowest_k(root, required_slot_keys, nodes, 0.0)
    return root.obligations[slot_key] if slot_key else None


def _frontier_confident(
    frontier: List[RootHypothesis], required_slot_keys: List[str], nodes: Dict[str, Node], tau: float
) -> bool:
    if not frontier:
        return False
    for root in frontier:
        if root.status != "SCOPED":
            return False
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            if not node_key:
                return False
            node = nodes.get(node_key)
            if not node:
                return False
            if float(node.k) < float(tau):
                return False
    return True


def _legal_next_for_root(
    root: RootHypothesis,
    required_slot_keys: List[str],
    tau: float,
    nodes: Dict[str, Node],
    credits_left: int,
) -> Optional[Tuple[str, str]]:
    if root.status == "UNSCOPED":
        return ("DECOMPOSE", root.root_id)
    if any(k not in root.obligations for k in required_slot_keys):
        return ("DECOMPOSE", root.root_id)

    slot_key = _select_slot_lowest_k(root, required_slot_keys, nodes, tau)
    if not slot_key:
        return None
    slot_key_node = root.obligations[slot_key]
    slot = nodes.get(slot_key_node)
    if not slot:
        return None

    if _node_needs_decomposition(slot, tau, credits_left):
        return ("DECOMPOSE", slot.node_key)

    child_decompose = _select_decompose_in_subtree(slot, nodes, tau, credits_left)
    if child_decompose:
        return ("DECOMPOSE", child_decompose)

    child_key = _select_unassessed_in_subtree(slot, nodes)
    if child_key:
        return ("EVALUATE", child_key)

    if not slot.assessed:
        return ("EVALUATE", slot.node_key)

    return None


def run_session(request: SessionRequest, deps: RunSessionDeps) -> SessionResult:
    _validate_request(request)

    hypothesis_set = _init_hypothesis_set(request)
    required_slot_keys = _required_slot_keys(request)
    required_slot_roles = _required_slot_roles(request)

    named_root_ids = [rid for rid in hypothesis_set.roots if rid != H_OTHER_ID]
    deps.audit_sink.append(
        AuditEvent("SESSION_INITIALIZED", {"roots": list(hypothesis_set.roots.keys()), "ledger": dict(hypothesis_set.ledger)})
    )

    sum_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
    branch = "S<=1" if sum_named <= 1.0 else "S>1"
    enforce_absorber(hypothesis_set.ledger, named_root_ids)
    deps.audit_sink.append(AuditEvent("OTHER_ABSORBER_ENFORCED", {"branch": branch, "sum_named": sum_named}))
    deps.audit_sink.append(AuditEvent("INVARIANT_SUM_TO_ONE_CHECK", {"total": sum(hypothesis_set.ledger.values())}))

    credits_remaining = int(request.credits)
    total_credits_spent = 0
    operation_log: List[Dict[str, object]] = []

    run_mode = request.run_mode or "until_credits_exhausted"
    op_limit = request.run_count if run_mode in {"operations", "evaluation", "evaluations_children"} else None

    pre_scoped = request.pre_scoped_roots or []
    slot_k_min = request.slot_k_min or {}
    slot_initial_p = request.slot_initial_p or {}
    force_scope_fail_root = request.force_scope_fail_root

    nodes: Dict[str, Node] = {}

    def record_op(op_type: str, target_id: str, before: int, after: int) -> None:
        operation_log.append({"op_type": op_type, "target_id": target_id, "credits_before": before, "credits_after": after})
        deps.audit_sink.append(AuditEvent("OP_EXECUTED", {"op_type": op_type, "target_id": target_id, "credits_before": before, "credits_after": after}))

    def apply_ledger_update(root: RootHypothesis) -> None:
        slot_p_values = []
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            if not node_key:
                continue
            node = nodes.get(node_key)
            if node:
                slot_p_values.append(node.p)
        if not slot_p_values:
            slot_p_values = [1.0]
        m = 1.0
        for v in slot_p_values:
            m *= float(v)
        deps.audit_sink.append(AuditEvent("MULTIPLIER_COMPUTED", {"root_id": root.root_id, "slot_p_values": slot_p_values, "m": m}))

        p_base = float(hypothesis_set.ledger.get(root.root_id, 0.0))
        p_prop = p_base * m
        deps.audit_sink.append(AuditEvent("P_PROP_COMPUTED", {"root_id": root.root_id, "p_base": p_base, "p_prop": p_prop}))

        alpha = float(request.config.alpha)
        p_new = p_base + alpha * (p_prop - p_base)
        p_new = _clamp_probability(p_new)
        hypothesis_set.ledger[root.root_id] = p_new
        deps.audit_sink.append(AuditEvent("DAMPING_APPLIED", {"root_id": root.root_id, "alpha": alpha, "p_base": p_base, "p_new": p_new}))

        sum_named_local = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
        branch_local = "S<=1" if sum_named_local <= 1.0 else "S>1"
        enforce_absorber(hypothesis_set.ledger, named_root_ids)
        deps.audit_sink.append(AuditEvent("OTHER_ABSORBER_ENFORCED", {"branch": branch_local, "sum_named": sum_named_local}))
        deps.audit_sink.append(AuditEvent("INVARIANT_SUM_TO_ONE_CHECK", {"total": sum(hypothesis_set.ledger.values())}))

    def evaluate_node(root: RootHypothesis, node_key: str) -> None:
        node = nodes.get(node_key)
        if node is None:
            return

        outcome = deps.evaluator.evaluate(node_key) or {}
        previous_p = float(node.p)
        proposed_p = float(outcome.get("p", previous_p))

        refs_text = str(outcome.get("evidence_refs", "")).strip()
        has_refs = bool(refs_text and refs_text != "(empty)")
        if not has_refs:
            delta = max(min(proposed_p - previous_p, 0.05), -0.05)
            proposed_p = previous_p + delta
            deps.audit_sink.append(AuditEvent("CONSERVATIVE_DELTA_ENFORCED", {"node_key": node_key, "p_before": previous_p, "p_after": proposed_p}))

        node.p = _clamp_probability(float(proposed_p))
        node.assessed = True

        rubric = {k: int(outcome[k]) for k in ("A", "B", "C", "D") if k in outcome and str(outcome[k]).isdigit()}
        if rubric:
            node.k, guardrail = _derive_k_from_rubric(rubric)
            if guardrail:
                deps.audit_sink.append(AuditEvent("K_GUARDRAIL_APPLIED", {"node_key": node_key, "k": node.k}))

        deps.audit_sink.append(AuditEvent("NODE_EVALUATED", {"node_key": node_key, "p": node.p, "k": node.k}))

        for parent in nodes.values():
            if parent.decomp_type == "AND" and node_key in parent.children:
                aggregated, details = _aggregate_soft_and(parent, nodes)
                parent.p = _clamp_probability(float(aggregated))
                deps.audit_sink.append(
                    AuditEvent("SOFT_AND_COMPUTED", {"node_key": parent.node_key, **details, "m": parent.p})
                )

        assessed_slots = []
        for slot_key in required_slot_keys:
            node_key_for_slot = root.obligations.get(slot_key)
            if not node_key_for_slot:
                continue
            slot_node = nodes.get(node_key_for_slot)
            if slot_node and slot_node.assessed:
                assessed_slots.append(slot_node)
        if assessed_slots:
            root.k_root = min(n.k for n in assessed_slots)

        apply_ledger_update(root)

    for rid in pre_scoped:
        r = hypothesis_set.roots.get(rid)
        if not r:
            continue
        decomp = deps.decomposer.decompose(rid)
        _decompose_root(
            deps,
            r,
            required_slot_keys,
            required_slot_roles,
            decomp,
            slot_k_min.get(rid),
            slot_initial_p,
            nodes,
        )
        for slot_key in list(r.obligations.keys()):
            slot_node_key = r.obligations.get(slot_key)
            if not slot_node_key:
                continue
            slot_decomp = deps.decomposer.decompose(slot_node_key)
            _apply_node_decomposition(deps, slot_node_key, slot_decomp, nodes)

    def frontier_ids() -> Tuple[Optional[str], List[RootHypothesis]]:
        return _compute_frontier([root for root_id, root in hypothesis_set.roots.items() if root_id != H_OTHER_ID], hypothesis_set.ledger, request.config.epsilon)

    stop_reason: Optional[StopReason] = None
    rr_index = 0
    last_frontier_signature: Optional[Tuple[str, ...]] = None

    if run_mode == "start_only":
        if credits_remaining <= 0:
            stop_reason = StopReason.CREDITS_EXHAUSTED
    else:
        while True:
            if credits_remaining <= 0:
                stop_reason = StopReason.CREDITS_EXHAUSTED
                break
            if op_limit is not None and total_credits_spent >= int(op_limit):
                stop_reason = StopReason.OP_LIMIT_REACHED
                break

            leader_id, frontier = frontier_ids()
            deps.audit_sink.append(
                AuditEvent("FRONTIER_DEFINED", {"leader_id": leader_id, "frontier": [r.root_id for r in frontier]})
            )
            signature = tuple(r.root_id for r in frontier)
            if signature != last_frontier_signature:
                last_frontier_signature = signature
                if len(frontier) > 1:
                    deps.audit_sink.append(
                        AuditEvent(
                            "TIE_BREAKER_APPLIED",
                            {"ordered_frontier": list(signature)},
                        )
                    )

            if not frontier:
                stop_reason = StopReason.NO_HYPOTHESES
                break
            if (
                run_mode in {"until_stops", "operations"}
                and not force_scope_fail_root
                and _frontier_confident(frontier, required_slot_keys, nodes, request.config.tau)
            ):
                stop_reason = StopReason.FRONTIER_CONFIDENT
                break

            if run_mode == "evaluation":
                target_root = frontier[rr_index % len(frontier)]
                rr_index += 1
                node_key = request.run_target
                if not node_key:
                    node_key = _select_child_for_evaluation(target_root, required_slot_keys, nodes)
                if not node_key:
                    node_key = _select_slot_for_evaluation(target_root, required_slot_keys, nodes)
                if not node_key:
                    if all(_select_slot_for_evaluation(r, required_slot_keys, nodes) is None for r in frontier):
                        stop_reason = StopReason.NO_LEGAL_OP
                        break
                    continue

                before = credits_remaining
                credits_remaining -= 1
                total_credits_spent += 1
                target_root.credits_spent += 1
                evaluate_node(target_root, node_key)
                record_op("EVALUATE", node_key, before, credits_remaining)
                continue

            if run_mode == "evaluations_children":
                target_root = frontier[rr_index % len(frontier)]
                rr_index += 1
                child_slots = []
                for k in required_slot_keys:
                    node_key = target_root.obligations.get(k)
                    node = nodes.get(node_key) if node_key else None
                    if node and node.children:
                        child_slots.append(k)
                if child_slots:
                    slot_order = _slot_order_map(required_slot_keys)
                    child_slots.sort(key=lambda k: slot_order.get(k, 10_000))
                    slot = nodes.get(target_root.obligations[child_slots[0]])
                else:
                    available = [k for k in required_slot_keys if k in target_root.obligations]
                    if not available:
                        if all(not any(k in r.obligations for k in required_slot_keys) for r in frontier):
                            stop_reason = StopReason.NO_LEGAL_OP
                            break
                        continue
                    selected_slot = _select_slot_lowest_k(target_root, required_slot_keys, nodes, request.config.tau)
                    if not selected_slot:
                        stop_reason = StopReason.NO_LEGAL_OP
                        break
                    slot_key_node = target_root.obligations.get(selected_slot)
                    slot = nodes.get(slot_key_node) if slot_key_node else None
                if not slot:
                    if all(not any(k in r.obligations for k in required_slot_keys) for r in frontier):
                        stop_reason = StopReason.NO_LEGAL_OP
                        break
                    continue
                if slot.children:
                    for child_key in _flatten_subtree(slot, nodes):
                        if credits_remaining <= 0:
                            stop_reason = StopReason.CREDITS_EXHAUSTED
                            break
                        if op_limit is not None and total_credits_spent >= int(op_limit):
                            stop_reason = StopReason.OP_LIMIT_REACHED
                            break
                        before = credits_remaining
                        credits_remaining -= 1
                        total_credits_spent += 1
                        target_root.credits_spent += 1
                        evaluate_node(target_root, child_key)
                        record_op("EVALUATE", child_key, before, credits_remaining)
                    if stop_reason is not None:
                        break
                else:
                    before = credits_remaining
                    credits_remaining -= 1
                    total_credits_spent += 1
                    target_root.credits_spent += 1
                    evaluate_node(target_root, slot.node_key)
                    record_op("EVALUATE", slot.node_key, before, credits_remaining)
                continue

            target_root = frontier[rr_index % len(frontier)]
            rr_index += 1

            nxt = _legal_next_for_root(target_root, required_slot_keys, request.config.tau, nodes, credits_remaining)
            if nxt is None:
                if all(
                    _legal_next_for_root(r, required_slot_keys, request.config.tau, nodes, credits_remaining)
                    is None
                    for r in frontier
                ):
                    stop_reason = StopReason.NO_LEGAL_OP
                    break
                continue

            op_type, target_id = nxt

            before = credits_remaining
            credits_remaining -= 1
            total_credits_spent += 1
            target_root.credits_spent += 1

            if op_type == "DECOMPOSE":
                if ":" in target_id:
                    slot_decomp = deps.decomposer.decompose(target_id)
                    _apply_node_decomposition(deps, target_id, slot_decomp, nodes)
                else:
                    if force_scope_fail_root and target_root.root_id == force_scope_fail_root:
                        decomp = {"ok": False}
                    else:
                        decomp = deps.decomposer.decompose(target_root.root_id)
                    _decompose_root(
                        deps,
                        target_root,
                        required_slot_keys,
                        required_slot_roles,
                        decomp,
                        slot_k_min.get(target_root.root_id),
                        slot_initial_p,
                        nodes,
                    )
                record_op("DECOMPOSE", target_id, before, credits_remaining)
            else:
                evaluate_node(target_root, target_id)
                record_op("EVALUATE", target_id, before, credits_remaining)

            if run_mode == "operations" and op_limit is not None and total_credits_spent >= int(op_limit):
                stop_reason = StopReason.OP_LIMIT_REACHED
                break

            if run_mode == "until_credits_exhausted":
                if credits_remaining <= 0:
                    stop_reason = StopReason.CREDITS_EXHAUSTED
                    break
                continue

    deps.audit_sink.append(AuditEvent("STOP_REASON_RECORDED", {"stop_reason": stop_reason.value if stop_reason else None}))

    roots_view = {
        root_id: {
            "id": root.root_id,
            "statement": root.statement,
            "exclusion_clause": root.exclusion_clause,
            "canonical_id": root.canonical_id,
            "status": root.status,
            "k_root": root.k_root,
            "p_ledger": float(hypothesis_set.ledger.get(root_id, 0.0)),
            "credits_spent": root.credits_spent,
            "obligations": {
                slot_key: {
                    "node_key": node.node_key,
                    "statement": node.statement,
                    "role": node.role,
                    "p": node.p,
                    "k": node.k,
                    "assessed": node.assessed,
                    "children": list(node.children),
                    "decomp_type": node.decomp_type,
                    "coupling": node.coupling,
                }
                for slot_key, node_key in root.obligations.items()
                if (node := nodes.get(node_key))
            },
        }
        for root_id, root in hypothesis_set.roots.items()
    }

    nodes_view = {
        node_key: {
            "node_key": node.node_key,
            "statement": node.statement,
            "role": node.role,
            "p": node.p,
            "k": node.k,
            "assessed": node.assessed,
            "children": list(node.children),
            "decomp_type": node.decomp_type,
            "coupling": node.coupling,
        }
        for node_key, node in nodes.items()
    }

    return SessionResult(
        roots=roots_view,
        ledger=dict(hypothesis_set.ledger),
        nodes=nodes_view,
        audit=[{"event_type": e.event_type, "payload": e.payload} for e in deps.audit_sink.events],
        stop_reason=stop_reason,
        credits_remaining=credits_remaining,
        total_credits_spent=total_credits_spent,
        operation_log=operation_log,
    )
