from __future__ import annotations

import hashlib
import json
import math
from typing import Dict, Iterable, List, Optional, Tuple

from abductio_core.application.dto import EvidenceItem, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.result import SessionResult, StopReason
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.canonical import canonical_id_for_statement
from abductio_core.domain.invariants import H_NOA_ID, H_UND_ID, enforce_open_world
from abductio_core.domain.model import HypothesisSet, Node, RootHypothesis


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_whitespace(text: str) -> str:
    return " ".join(str(text).split())


def _logit(p: float) -> float:
    p = _clip(p, 1e-6, 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _safe_log(p: float) -> float:
    return math.log(max(p, 1e-12))


def _logsumexp(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    peak = max(vals)
    total = sum(math.exp(v - peak) for v in vals)
    return peak + math.log(total)


def _normalize_log_ledger(log_ledger: Dict[str, float]) -> Dict[str, float]:
    lse = _logsumexp(log_ledger.values())
    return {key: math.exp(value - lse) for key, value in log_ledger.items()}

def _evidence_item_payload(item: EvidenceItem) -> Dict[str, object]:
    return {
        "id": item.id,
        "source": item.source,
        "text": item.text,
        "location": item.location,
        "metadata": dict(item.metadata),
    }


def _hash_json_payload(payload: Dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _hash_evidence_item(item: EvidenceItem) -> str:
    return _hash_json_payload(_evidence_item_payload(item))


def _hash_evidence_packet(evidence_index: Dict[str, EvidenceItem]) -> str:
    ordered = []
    for evidence_id in sorted(evidence_index.keys()):
        item = evidence_index[evidence_id]
        ordered.append(f"{evidence_id}:{_hash_evidence_item(item)}")
    digest = hashlib.sha256("|".join(ordered).encode("utf-8")).hexdigest()
    return digest


def _hash_search_snapshot(items: List[EvidenceItem]) -> str:
    ordered = [f"{item.id}:{_hash_evidence_item(item)}" for item in sorted(items, key=lambda i: i.id)]
    return hashlib.sha256("|".join(ordered).encode("utf-8")).hexdigest()


def _validate_request(request: SessionRequest) -> None:
    if request.credits < 0:
        raise ValueError("credits must be non-negative")
    for attr in ("tau", "epsilon", "alpha"):
        value = getattr(request.config, attr)
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{attr} must be within [0,1]")
    for attr in ("gamma_noa", "gamma_und"):
        value = getattr(request.config, attr)
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{attr} must be within [0,1]")
    if request.config.gamma_noa + request.config.gamma_und > 1.0:
        raise ValueError("gamma_noa + gamma_und must be <= 1")
    if request.config.beta < 0.0:
        raise ValueError("beta must be non-negative")
    if request.config.W <= 0.0:
        raise ValueError("W must be greater than 0")
    if request.config.lambda_voi < 0.0:
        raise ValueError("lambda_voi must be non-negative")
    if request.config.world_mode not in {"open", "closed"}:
        raise ValueError("world_mode must be 'open' or 'closed'")
    if not (0.0 <= float(request.config.rho_eval_min) <= 1.0):
        raise ValueError("rho_eval_min must be within [0,1]")
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
        return ["availability", "fit_to_key_features", "defeater_resistance"]
    return [row["slot_key"] for row in required_slots if "slot_key" in row]


def _required_slot_roles(request: SessionRequest) -> Dict[str, str]:
    required_slots = request.required_slots
    if not required_slots:
        return {
            "availability": "NEC",
            "fit_to_key_features": "NEC",
            "defeater_resistance": "NEC",
        }
    return {row["slot_key"]: row.get("role", "NEC") for row in required_slots if "slot_key" in row}


def _evidence_index(request: SessionRequest) -> Dict[str, EvidenceItem]:
    items = request.evidence_items or []
    index: Dict[str, EvidenceItem] = {}
    for item in items:
        if isinstance(item, EvidenceItem):
            evidence_id = item.id
            index[evidence_id] = item
            continue
        if isinstance(item, dict):
            evidence_id = str(item.get("id") or item.get("evidence_id") or "").strip()
            if not evidence_id:
                continue
            index[evidence_id] = EvidenceItem(
                id=evidence_id,
                source=str(item.get("source", "")),
                text=str(item.get("text", "")),
                location=item.get("location"),
                metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
            )
    return index


def _node_statement_map(decomposition: Dict[str, str]) -> Dict[str, str]:
    return {
        "availability": decomposition.get("availability_statement", ""),
        "fit_to_key_features": decomposition.get("fit_to_key_features_statement", ""),
        "defeater_resistance": decomposition.get("defeater_resistance_statement", ""),
    }


def _build_search_query(scope: str, root: RootHypothesis, slot_key: str, depth: int) -> str:
    return f"scope={scope} | hypothesis={root.root_id} | statement={root.statement} | slot={slot_key} | depth={depth}"


def _open_world_gammas(config: SessionConfig) -> Tuple[float, float]:
    gamma_noa = float(config.gamma_noa)
    gamma_und = float(config.gamma_und)
    if gamma_noa == 0.0 and gamma_und == 0.0 and float(config.gamma) > 0.0:
        legacy = float(config.gamma)
        return legacy / 2.0, legacy / 2.0
    return gamma_noa, gamma_und


def _init_hypothesis_set(request: SessionRequest) -> HypothesisSet:
    roots: Dict[str, RootHypothesis] = {}
    ledger: Dict[str, float] = {}
    named_roots = request.roots
    count_named = len(named_roots)
    gamma_noa, gamma_und = _open_world_gammas(request.config)
    gamma_total = gamma_noa + gamma_und
    base_p = (1.0 - gamma_total) / count_named if count_named else 0.0

    for root in named_roots:
        canonical_id = canonical_id_for_statement(root.statement)
        roots[root.root_id] = RootHypothesis(
            root_id=root.root_id,
            statement=root.statement,
            exclusion_clause=root.exclusion_clause,
            canonical_id=canonical_id,
        )
        ledger[root.root_id] = base_p

    if request.config.world_mode != "closed":
        roots[H_NOA_ID] = RootHypothesis(
            root_id=H_NOA_ID,
            statement="None of the above",
            exclusion_clause="Not any named hypothesis",
            canonical_id=canonical_id_for_statement("None of the above"),
            status="NOA",
        )
        roots[H_UND_ID] = RootHypothesis(
            root_id=H_UND_ID,
            statement="Underdetermined",
            exclusion_clause="Insufficient evidence to discriminate",
            canonical_id=canonical_id_for_statement("Underdetermined"),
            status="UND",
        )
        if count_named:
            ledger[H_NOA_ID] = gamma_noa
            ledger[H_UND_ID] = gamma_und
        else:
            ledger[H_NOA_ID] = 0.5
            ledger[H_UND_ID] = 0.5

    if request.initial_ledger:
        ledger.update(request.initial_ledger)

    return HypothesisSet(roots=roots, ledger=ledger)


def _compute_frontier(
    roots: Iterable[RootHypothesis],
    ledger: Dict[str, float],
    epsilon: float,
    lambda_voi: float,
) -> Tuple[Optional[str], List[RootHypothesis]]:
    named_roots = list(roots)
    if not named_roots:
        return None, []
    def priority(root: RootHypothesis) -> float:
        p = float(ledger.get(root.root_id, 0.0))
        n = max(1, int(root.credits_spent))
        return (p * (1.0 - p) + (lambda_voi / n)) * (1.0 - float(root.k_root))

    ordered = sorted(named_roots, key=lambda r: (-priority(r), r.canonical_id))
    leader = ordered[0]
    leader_score = priority(leader)
    frontier = [r for r in ordered if priority(r) >= leader_score - epsilon]
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
        return 0.5, {"p_min": 0.5, "p_prod": 0.5, "c": float(node.coupling or 0.0)}
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
                        "children_spec": [],
                        "llm": decomposition.get("_provenance"),
                    },
                )
            )
        return False

    node.decomp_type = str(decomposition.get("type") or "")
    node.coupling = decomposition.get("coupling")
    node.children = []

    children_spec: List[Dict[str, object]] = []
    for child in decomposition.get("children", []):
        if not isinstance(child, dict):
            continue
        child_id = child.get("child_id") or child.get("id")
        statement = str(child.get("statement", ""))
        if not child_id and not statement:
            continue
        canonical_child_id = canonical_id_for_statement(statement) if statement else str(child_id)
        child_node_key = f"{node_key}:{canonical_child_id}"
        nodes[child_node_key] = Node(
            node_key=child_node_key,
            statement=statement,
            role=str(child.get("role", "NEC")),
            p=0.5,
            k=0.15,
            assessed=False,
        )
        node.children.append(child_node_key)
        children_spec.append(
            {
                "child_id": child_id,
                "canonical_child_id": canonical_child_id,
                "statement": statement,
                "role": child.get("role", "NEC"),
                "node_key": child_node_key,
                "falsifiable": child.get("falsifiable"),
                "test_procedure": child.get("test_procedure"),
                "overlap_with_siblings": child.get("overlap_with_siblings", []),
            }
        )

    node.children.sort()
    deps.audit_sink.append(
        AuditEvent(
            event_type="NODE_REFINED_REQUIREMENTS",
            payload={
                "node_key": node_key,
                "type": node.decomp_type,
                "coupling": node.coupling,
                "children": list(node.children),
                "children_spec": children_spec,
                "llm": decomposition.get("_provenance"),
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
        deps.audit_sink.append(
            AuditEvent(
                "ROOT_DECOMPOSED",
                {
                    "root_id": root.root_id,
                    "ok": False,
                    "slot_statements": {},
                    "llm": decomposition.get("_provenance"),
                },
            )
        )
        return

    statement_map = _node_statement_map(decomposition)
    deps.audit_sink.append(
        AuditEvent(
            "ROOT_DECOMPOSED",
            {
                "root_id": root.root_id,
                "ok": True,
                "slot_statements": dict(statement_map),
                "llm": decomposition.get("_provenance"),
            },
        )
    )
    for slot_key in required_slot_keys:
        if slot_key in root.obligations:
            continue
        node_key = f"{root.root_id}:{slot_key}"
        statement = statement_map.get(slot_key) or ""
        role = required_slot_roles.get(slot_key, "NEC")
        initial_p = float(slot_initial_p.get(node_key, 0.5))
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
        slot_nodes = [
            nodes[k]
            for slot_key, k in root.obligations.items()
            if k in nodes and required_slot_roles.get(slot_key, "NEC") == "NEC"
        ]
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
    evidence_index = _evidence_index(request)
    evidence_packet_hash = _hash_evidence_packet(evidence_index)

    named_root_ids = [rid for rid in hypothesis_set.roots if rid not in {H_NOA_ID, H_UND_ID}]
    deps.audit_sink.append(
        AuditEvent(
            "SESSION_INITIALIZED",
            {
                "roots": list(hypothesis_set.roots.keys()),
                "ledger": dict(hypothesis_set.ledger),
                "roots_spec": [
                    {
                        "root_id": root.root_id,
                        "statement": root.statement,
                        "exclusion_clause": root.exclusion_clause,
                        "canonical_id": root.canonical_id,
                    }
                    for root in hypothesis_set.roots.values()
                ],
                "config": {
                    "tau": request.config.tau,
                    "epsilon": request.config.epsilon,
                    "gamma_noa": request.config.gamma_noa,
                    "gamma_und": request.config.gamma_und,
                    "gamma": request.config.gamma,
                    "alpha": request.config.alpha,
                    "beta": request.config.beta,
                    "W": request.config.W,
                    "lambda_voi": request.config.lambda_voi,
                    "world_mode": request.config.world_mode,
                    "rho_eval_min": request.config.rho_eval_min,
                },
                "required_slots": request.required_slots or [],
                "framing": request.framing,
                "initial_ledger": dict(request.initial_ledger or {}),
                "slot_k_min": dict(request.slot_k_min or {}),
                "slot_initial_p": dict(request.slot_initial_p or {}),
                "evidence_items": [_evidence_item_payload(item) for item in evidence_index.values()],
                "evidence_packet_hash": evidence_packet_hash,
            },
        )
    )
    if request.framing:
        deps.audit_sink.append(AuditEvent("FRAMING_RECORDED", {"framing": request.framing}))

    seen_canonical: Dict[str, List[str]] = {}
    for root in hypothesis_set.roots.values():
        seen_canonical.setdefault(root.canonical_id, []).append(root.root_id)
    for cid, ids in seen_canonical.items():
        if len(ids) > 1:
            deps.audit_sink.append(AuditEvent("MECE_VIOLATION", {"canonical_id": cid, "root_ids": list(ids)}))

    if H_NOA_ID in hypothesis_set.ledger or H_UND_ID in hypothesis_set.ledger:
        sum_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
        branch = "S<=1" if sum_named <= 1.0 else "S>1"
        enforce_open_world(hypothesis_set.ledger, named_root_ids)
        deps.audit_sink.append(
            AuditEvent(
                "OPEN_WORLD_RESIDUALS_ENFORCED",
                {
                    "branch": branch,
                    "sum_named": sum_named,
                    "gamma_noa": request.config.gamma_noa,
                    "gamma_und": request.config.gamma_und,
                },
            )
        )
        deps.audit_sink.append(
            AuditEvent("INVARIANT_SUM_TO_ONE_CHECK", {"total": sum(hypothesis_set.ledger.values())})
        )
    else:
        total = sum(hypothesis_set.ledger.values())
        if total > 0.0:
            hypothesis_set.ledger = {k: v / total for k, v in hypothesis_set.ledger.items()}
        deps.audit_sink.append(
            AuditEvent(
                "CLOSED_WORLD_RENORMALIZED",
                {"total": sum(hypothesis_set.ledger.values()), "ledger": dict(hypothesis_set.ledger)},
            )
        )

    log_ledger: Dict[str, float] = {}
    for rid in named_root_ids:
        log_ledger[rid] = _safe_log(float(hypothesis_set.ledger.get(rid, 0.0)))

    credits_remaining = int(request.credits)
    total_credits_spent = 0
    credits_evaluated = 0
    operation_log: List[Dict[str, object]] = []

    run_mode = request.run_mode or "until_credits_exhausted"
    op_limit = request.run_count if run_mode in {"operations", "evaluation", "evaluations_children"} else None

    pre_scoped = request.pre_scoped_roots or []
    slot_k_min = request.slot_k_min or {}
    slot_initial_p = request.slot_initial_p or {}
    force_scope_fail_root = request.force_scope_fail_root

    nodes: Dict[str, Node] = {}
    node_evidence_ids: Dict[str, List[str]] = {}
    node_explanations: Dict[str, Dict[str, object]] = {}

    def record_op(
        op_type: str, target_id: str, before: int, after: int, extra: Optional[Dict[str, object]] = None
    ) -> None:
        operation_log.append({"op_type": op_type, "target_id": target_id, "credits_before": before, "credits_after": after})
        payload = {"op_type": op_type, "target_id": target_id, "credits_before": before, "credits_after": after}
        if extra:
            payload.update(extra)
        deps.audit_sink.append(AuditEvent("OP_EXECUTED", payload))

    w_applied: Dict[Tuple[str, str], float] = {}

    search_plan: List[Tuple[str, str, int, int]] = []
    search_cursor = 0

    def _build_search_plan() -> None:
        nonlocal search_plan
        if not getattr(request, "search_enabled", False):
            search_plan = []
            return
        quota = int(getattr(request, "search_quota_per_slot", 0) or getattr(request, "max_search_per_node", 0) or 0)
        max_depth = int(getattr(request, "max_search_depth", 0) or 0)
        if quota <= 0 or max_depth < 0:
            search_plan = []
            return
        named_roots = [hypothesis_set.roots[rid] for rid in named_root_ids if rid in hypothesis_set.roots]
        if not named_roots or not required_slot_keys:
            search_plan = []
            return
        root_order = sorted(named_roots, key=lambda root: root.canonical_id)
        plan: List[Tuple[str, str, int, int]] = []
        for depth in range(max_depth + 1):
            for slot_key in required_slot_keys:
                for root in root_order:
                    for idx in range(quota):
                        plan.append((root.root_id, slot_key, depth, idx))
        search_plan = plan

    def _next_search_target() -> Optional[Tuple[str, str, int, int]]:
        nonlocal search_cursor
        if search_cursor >= len(search_plan):
            return None
        target = search_plan[search_cursor]
        search_cursor += 1
        return target

    def _execute_search(root_id: str, slot_key: str, depth: int, quota_index: int) -> None:
        nonlocal credits_remaining, total_credits_spent, evidence_packet_hash
        root = hypothesis_set.roots.get(root_id)
        if not root or credits_remaining <= 0:
            return
        query = _build_search_query(request.scope, root, slot_key, depth)
        metadata = {
            "root_id": root_id,
            "slot_key": slot_key,
            "depth": depth,
            "quota_index": quota_index,
            "deterministic": bool(getattr(request, "search_deterministic", False)),
        }
        limit = 1
        items = deps.searcher.search(query, limit=limit, metadata=metadata) or []
        if len(items) > limit:
            items = items[:limit]
        snapshot_hash = _hash_search_snapshot(items)
        new_ids: List[str] = []
        for item in items:
            if item.id not in evidence_index:
                evidence_index[item.id] = item
                new_ids.append(item.id)
        evidence_packet_hash = _hash_evidence_packet(evidence_index)
        payload = {
            "root_id": root_id,
            "slot_key": slot_key,
            "depth": depth,
            "query": query,
            "search_snapshot_hash": snapshot_hash,
            "new_evidence_ids": new_ids,
            "evidence_packet_hash": evidence_packet_hash,
        }
        deps.audit_sink.append(AuditEvent("SEARCH_EXECUTED", payload))
        before = credits_remaining
        credits_remaining -= 1
        total_credits_spent += 1
        record_op(
            "SEARCH",
            f"{root_id}:{slot_key}:{depth}:{quota_index}",
            before,
            credits_remaining,
            {
                "root_id": root_id,
                "slot_key": slot_key,
                "depth": depth,
                "query": query,
                "search_snapshot_hash": snapshot_hash,
                "evidence_packet_hash": evidence_packet_hash,
            },
        )

    def _slot_weight(node: Node, weight_cap: float) -> float:
        if not node.assessed:
            return 0.0
        p = _clip(float(node.p), 1e-6, 1.0 - 1e-6)
        ratio = p / 0.5
        return _clip(math.log(ratio), -weight_cap, weight_cap)

    def _update_open_world_residuals() -> None:
        if request.config.world_mode == "closed":
            return
        if not named_root_ids:
            return
        # Mismatch: best (minimum) residual over named roots.
        slot_count = max(1, len(required_slot_keys))
        mismatches: List[float] = []
        for root_id in named_root_ids:
            root = hypothesis_set.roots.get(root_id)
            if not root:
                continue
            total = 0.0
            for slot_key in required_slot_keys:
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if node:
                    p = float(node.p)
                    k = float(node.k)
                else:
                    p = 0.5
                    k = 0.15
                total += (1.0 - p) * k
            mismatches.append(total / slot_count)
        M = min(mismatches) if mismatches else 0.0

        # Underdetermination from validity deficits on assessed slots.
        validity_terms: List[float] = []
        for root_id in named_root_ids:
            root = hypothesis_set.roots.get(root_id)
            if not root:
                continue
            for slot_key in required_slot_keys:
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if node and node.assessed:
                    validity_terms.append(1.0 - float(node.validity))
        U = (sum(validity_terms) / len(validity_terms)) if validity_terms else 0.0

        eta_M = 0.25
        eta_U = 0.25
        gamma_min = 0.01
        gamma_max = 0.60
        base_noa, base_und = _open_world_gammas(request.config)
        gamma_noa = _clip(base_noa + eta_M * M, gamma_min, gamma_max)
        gamma_und = _clip(base_und + eta_U * U, gamma_min, gamma_max)
        if gamma_noa + gamma_und >= 0.99:
            scale = 0.99 / max(1e-9, gamma_noa + gamma_und)
            gamma_noa *= scale
            gamma_und *= scale

        total_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
        remaining = 1.0 - gamma_noa - gamma_und
        if total_named > 0.0:
            for rid in named_root_ids:
                hypothesis_set.ledger[rid] = hypothesis_set.ledger.get(rid, 0.0) * (remaining / total_named)
        hypothesis_set.ledger[H_NOA_ID] = gamma_noa
        hypothesis_set.ledger[H_UND_ID] = gamma_und
        deps.audit_sink.append(
            AuditEvent(
                "OPEN_WORLD_GAMMA_UPDATED",
                {"M": M, "U": U, "gamma_noa": gamma_noa, "gamma_und": gamma_und},
            )
        )

    _build_search_plan()

    def apply_ledger_update(root: RootHypothesis) -> None:
        weight_cap = float(request.config.W)
        p_base = float(hypothesis_set.ledger.get(root.root_id, 0.0))
        total_delta = 0.0
        slot_updates: List[Dict[str, object]] = []
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            if not node_key:
                continue
            node = nodes.get(node_key)
            if not node:
                continue
            w_new = _slot_weight(node, weight_cap)
            key = (root.root_id, slot_key)
            w_prev = w_applied.get(key, 0.0)
            delta = w_new - w_prev
            total_delta += float(delta)
            if abs(delta) > 0.0:
                pass
            w_applied[key] = w_new
            slot_updates.append(
                {
                    "root_id": root.root_id,
                    "slot_key": slot_key,
                    "p_slot": float(node.p),
                    "k_slot": float(node.k),
                    "w_prev": w_prev,
                    "w_new": w_new,
                    "delta_w": delta,
                    "clipped": abs(w_new) >= weight_cap and abs(abs(w_new) - weight_cap) <= 1e-12,
                    "clip_direction": "+W" if w_new > 0 else ("-W" if w_new < 0 else "0"),
                }
            )

        beta = float(request.config.beta)
        alpha = float(request.config.alpha)
        log_ledger[root.root_id] = log_ledger.get(root.root_id, _safe_log(p_base)) + (beta * total_delta)
        prop_named = _normalize_log_ledger(log_ledger) if log_ledger else {}
        p_prop = float(prop_named.get(root.root_id, p_base))
        p_damped = (1.0 - alpha) * p_base + alpha * p_prop
        deps.audit_sink.append(
            AuditEvent(
                "P_PROP_COMPUTED",
                {
                    "root_id": root.root_id,
                    "p_base": p_base,
                    "total_delta_w": total_delta,
                    "p_prop": p_prop,
                    "log_ledger": dict(log_ledger),
                },
            )
        )
        for payload in slot_updates:
            payload.update(
                {
                    "m": math.exp(total_delta),
                    "beta": beta,
                    "W": weight_cap,
                    "p_base": p_base,
                    "p_prop": p_prop,
                    "alpha": alpha,
                    "p_damped": p_damped,
                }
            )
            deps.audit_sink.append(AuditEvent("DELTA_W_APPLIED", payload))

        p_new = float(p_damped)
        if prop_named and len(named_root_ids) > 1:
            remaining_prop = 1.0 - p_prop
            remaining_new = 1.0 - p_new
            if remaining_prop <= 0.0:
                for rid in named_root_ids:
                    if rid != root.root_id:
                        prop_named[rid] = remaining_new / max(1, len(named_root_ids) - 1)
            else:
                scale = remaining_new / remaining_prop
                for rid in named_root_ids:
                    if rid != root.root_id:
                        prop_named[rid] = prop_named.get(rid, 0.0) * scale
            prop_named[root.root_id] = p_new
        elif prop_named:
            prop_named[root.root_id] = p_new
        else:
            prop_named = {root.root_id: p_new}

        for rid in named_root_ids:
            if rid in prop_named:
                hypothesis_set.ledger[rid] = prop_named[rid]
        if request.config.world_mode == "closed":
            total_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
            if total_named > 1.0:
                for rid in named_root_ids:
                    hypothesis_set.ledger[rid] = hypothesis_set.ledger.get(rid, 0.0) / total_named
                deps.audit_sink.append(
                    AuditEvent("CLOSED_WORLD_RENORMALIZED", {"total": sum(hypothesis_set.ledger.values()), "ledger": dict(hypothesis_set.ledger)})
                )
        else:
            _update_open_world_residuals()
        for rid in named_root_ids:
            log_ledger[rid] = _safe_log(float(hypothesis_set.ledger.get(rid, 0.0)))
        deps.audit_sink.append(
            AuditEvent("INVARIANT_SUM_TO_ONE_CHECK", {"total": sum(hypothesis_set.ledger.values())})
        )
        deps.audit_sink.append(
            AuditEvent(
                "DAMPING_APPLIED",
                {
                    "root_id": root.root_id,
                    "alpha": alpha,
                    "p_before": p_base,
                    "p_new": p_new,
                    "p_damped": float(hypothesis_set.ledger.get(root.root_id, 0.0)),
                },
            )
        )

    def evaluate_node(root: RootHypothesis, node_key: str) -> None:
        node = nodes.get(node_key)
        if node is None:
            return

        parts = node_key.split(":")
        root_id = parts[0] if parts else ""
        slot_key = parts[1] if len(parts) > 1 else ""
        child_id = ":".join(parts[2:]) if len(parts) > 2 else ""
        parent_statement = root.statement
        if child_id:
            parent_key = ":".join(parts[:2])
            parent_node = nodes.get(parent_key)
            if parent_node:
                parent_statement = parent_node.statement
        context = {
            "root_id": root_id,
            "root_statement": root.statement,
            "slot_key": slot_key,
            "child_id": child_id,
            "parent_statement": parent_statement,
            "role": node.role,
        }
        outcome = deps.evaluator.evaluate(
            node_key,
            node.statement,
            context,
            list(evidence_index.values()),
        ) or {}
        previous_p = float(node.p)
        proposed_p = float(outcome.get("p", previous_p))
        evidence_ids = outcome.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        evidence_ids = [str(item) for item in evidence_ids if isinstance(item, str)]
        missing_ids = [item for item in evidence_ids if item not in evidence_index]
        has_refs = bool(evidence_ids) and not missing_ids
        quotes = outcome.get("quotes")
        quotes_valid = True
        quote_mismatches: List[str] = []
        if quotes is not None and isinstance(quotes, list):
            for quote in quotes:
                if not isinstance(quote, dict):
                    quotes_valid = False
                    quote_mismatches.append("invalid_quote_object")
                    continue
                evidence_id = quote.get("evidence_id")
                exact_quote = quote.get("exact_quote")
                if not evidence_id or not exact_quote:
                    quotes_valid = False
                    quote_mismatches.append(str(evidence_id or "missing"))
                    continue
                item = evidence_index.get(str(evidence_id))
                if item and item.text:
                    if _normalize_whitespace(str(exact_quote)) not in _normalize_whitespace(item.text):
                        quotes_valid = False
                        quote_mismatches.append(str(evidence_id))

        if not has_refs:
            delta = max(min(proposed_p - previous_p, 0.05), -0.05)
            proposed_p = previous_p + delta
            deps.audit_sink.append(AuditEvent("CONSERVATIVE_DELTA_ENFORCED", {"node_key": node_key, "p_before": previous_p, "p_after": proposed_p}))

        node.p = _clamp_probability(float(proposed_p))
        node.assessed = True
        node.validity = 1.0 if (has_refs and quotes_valid) else 0.0
        node_evidence_ids[node_key] = list(evidence_ids)
        node_explanations[node_key] = {
            "evidence_ids": list(evidence_ids),
            "reasoning_summary": outcome.get("reasoning_summary"),
            "defeaters": outcome.get("defeaters"),
            "uncertainty_source": outcome.get("uncertainty_source"),
            "assumptions": outcome.get("assumptions"),
        }

        rubric = {k: int(outcome[k]) for k in ("A", "B", "C", "D") if k in outcome and str(outcome[k]).isdigit()}
        k_caps: List[Dict[str, object]] = []
        evidence_quality = outcome.get("evidence_quality")
        if not isinstance(evidence_quality, str):
            evidence_quality = "none" if not evidence_ids else "indirect"
        if not has_refs and rubric:
            rubric["A"] = 0
        if rubric:
            node.k, guardrail = _derive_k_from_rubric(rubric)
            if guardrail:
                deps.audit_sink.append(AuditEvent("K_GUARDRAIL_APPLIED", {"node_key": node_key, "k": node.k}))
            if not has_refs and node.k > 0.55:
                node.k = 0.55
                k_caps.append({"reason": "missing_evidence_ids", "cap": 0.55})
                deps.audit_sink.append(AuditEvent("K_EMPTY_REFS_CAPPED", {"node_key": node_key, "k": node.k}))
            quality_caps = {"weak": 0.35, "indirect": 0.55, "none": 0.35}
            if evidence_quality in quality_caps and node.k > quality_caps[evidence_quality]:
                node.k = quality_caps[evidence_quality]
                k_caps.append({"reason": f"evidence_quality_{evidence_quality}", "cap": node.k})
            if not quotes_valid and node.k > 0.35:
                node.k = 0.35
                k_caps.append({"reason": "quote_mismatch", "cap": node.k})
            assumptions = outcome.get("assumptions")
            if isinstance(assumptions, list) and assumptions and node.k > 0.55:
                node.k = 0.55
                k_caps.append({"reason": "assumptions_present", "cap": 0.55})

        deps.audit_sink.append(
            AuditEvent(
                "NODE_EVALUATED",
                {
                    "node_key": node_key,
                    "node": {
                        "statement": node.statement,
                        "role": node.role,
                        "decomp_type": node.decomp_type,
                        "coupling": node.coupling,
                    },
                    "p_before": previous_p,
                    "p_after": node.p,
                    "k": node.k,
                    "outcome": {
                        "p": outcome.get("p"),
                        "A": outcome.get("A"),
                        "B": outcome.get("B"),
                        "C": outcome.get("C"),
                        "D": outcome.get("D"),
                        "evidence_ids": evidence_ids,
                        "quotes": outcome.get("quotes"),
                        "evidence_quality": evidence_quality,
                        "reasoning_summary": outcome.get("reasoning_summary"),
                        "defeaters": outcome.get("defeaters"),
                        "uncertainty_source": outcome.get("uncertainty_source"),
                        "assumptions": outcome.get("assumptions"),
                    },
                    "derived": {
                        "has_evidence": has_refs,
                        "missing_evidence_ids": missing_ids,
                        "quotes_valid": quotes_valid,
                        "quote_mismatches": quote_mismatches,
                        "guardrail_applied": guardrail if rubric else False,
                        "conservative_delta_applied": not has_refs,
                        "k_caps": k_caps,
                        "validity": node.validity,
                    },
                    "evidence_packet_hash": evidence_packet_hash,
                    "llm": outcome.get("_provenance"),
                },
            )
        )

        for parent in nodes.values():
            if parent.decomp_type == "AND" and node_key in parent.children:
                aggregated, details = _aggregate_soft_and(parent, nodes)
                parent.p = _clamp_probability(float(aggregated))
                parent.assessed = True
                deps.audit_sink.append(
                    AuditEvent("SOFT_AND_COMPUTED", {"node_key": parent.node_key, **details, "m": parent.p})
                )
            if parent.decomp_type == "OR" and node_key in parent.children:
                children = [nodes[k] for k in parent.children if k in nodes and nodes[k].assessed]
                if not children:
                    parent.p = 0.5
                else:
                    parent.p = max(child.p for child in children)
                parent.assessed = True
                deps.audit_sink.append(
                    AuditEvent("SOFT_OR_COMPUTED", {"node_key": parent.node_key, "m": parent.p})
                )

        slot_nodes = []
        for slot_key in required_slot_keys:
            if required_slot_roles.get(slot_key, "NEC") != "NEC":
                continue
            node_key_for_slot = root.obligations.get(slot_key)
            if not node_key_for_slot:
                continue
            slot_node = nodes.get(node_key_for_slot)
            if slot_node:
                slot_nodes.append(slot_node)
        if slot_nodes:
            root.k_root = min(n.k for n in slot_nodes)

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
        return _compute_frontier(
            [root for root_id, root in hypothesis_set.roots.items() if root_id not in {H_NOA_ID, H_UND_ID}],
            hypothesis_set.ledger,
            request.config.epsilon,
            request.config.lambda_voi,
        )

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

            rho = float(request.config.rho_eval_min)
            eval_share = credits_evaluated / total_credits_spent if total_credits_spent > 0 else 1.0
            if run_mode not in {"evaluation", "evaluations_children"}:
                search_target = None
                if search_plan:
                    if eval_share >= rho:
                        search_target = _next_search_target()
                    else:
                        eval_available = False
                        for root in frontier:
                            nxt = _legal_next_for_root(root, required_slot_keys, request.config.tau, nodes, credits_remaining)
                            if nxt and nxt[0] == "EVALUATE":
                                eval_available = True
                                break
                        if not eval_available:
                            search_target = _next_search_target()
                if search_target:
                    _execute_search(*search_target)
                    continue

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
                credits_evaluated += 1
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
                    if selected_slot not in target_root.obligations:
                        if available:
                            selected_slot = available[0]
                        else:
                            if all(not any(k in r.obligations for k in required_slot_keys) for r in frontier):
                                stop_reason = StopReason.NO_LEGAL_OP
                                break
                            continue
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
                        credits_evaluated += 1
                        record_op("EVALUATE", child_key, before, credits_remaining)
                    if stop_reason is not None:
                        break
                else:
                    before = credits_remaining
                    credits_remaining -= 1
                    total_credits_spent += 1
                    target_root.credits_spent += 1
                    evaluate_node(target_root, slot.node_key)
                    credits_evaluated += 1
                    record_op("EVALUATE", slot.node_key, before, credits_remaining)
                continue

            candidates: List[Tuple[float, str, str, str, RootHypothesis]] = []
            lambda_voi = float(request.config.lambda_voi)
            for root in frontier:
                nxt = _legal_next_for_root(root, required_slot_keys, request.config.tau, nodes, credits_remaining)
                if nxt is None:
                    continue
                op_type, target_id = nxt
                node = nodes.get(target_id)
                p_val = float(node.p) if node else 0.5
                k_val = float(node.k) if node else float(root.k_root)
                if p_val <= 0.0 or p_val >= 1.0:
                    entropy = 0.0
                else:
                    entropy = -(p_val * math.log(p_val) + (1.0 - p_val) * math.log(1.0 - p_val))
                voi = float(hypothesis_set.ledger.get(root.root_id, 0.0)) * (1.0 - k_val) + lambda_voi * entropy
                deps.audit_sink.append(
                    AuditEvent(
                        "VOI_SCORED",
                        {
                            "root_id": root.root_id,
                            "target_id": target_id,
                            "voi": voi,
                            "p_node": p_val,
                            "k_node": k_val,
                            "lambda_voi": lambda_voi,
                        },
                    )
                )
                candidates.append((voi, root.canonical_id, op_type, target_id, root))

            if eval_share < rho:
                eval_candidates = [row for row in candidates if row[2] == "EVALUATE"]
                if eval_candidates:
                    candidates = eval_candidates
            if not candidates:
                stop_reason = StopReason.NO_LEGAL_OP
                break
            candidates.sort(key=lambda row: (-row[0], row[1], row[3]))
            _, _, op_type, target_id, target_root = candidates[0]

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
                credits_evaluated += 1
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

    def _weakest_slot(root: RootHypothesis) -> Optional[Dict[str, object]]:
        candidates: List[Tuple[float, float, str]] = []
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            if not node_key:
                continue
            node = nodes.get(node_key)
            if not node:
                continue
            candidates.append((float(node.k), float(node.p), slot_key))
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row[0], row[1], row[2]))
        k, p, slot_key = candidates[0]
        return {"slot": slot_key, "p": p, "k": k}

    explanations: Dict[str, Any] = {}

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
            "weakest_slot": _weakest_slot(root),
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

    for root_id, root in hypothesis_set.roots.items():
        slots = {}
        for slot_key, node_key in root.obligations.items():
            slots[slot_key] = node_explanations.get(node_key, {})
        evidence_ids = []
        for node_key in root.obligations.values():
            evidence_ids.extend(node_evidence_ids.get(node_key, []))
        explanations[root_id] = {
            "slot_explanations": slots,
            "evidence_ids": sorted(set(evidence_ids)),
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
        explanations=explanations,
        metadata={"framing": request.framing} if request.framing else {},
    )
