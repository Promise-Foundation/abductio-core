from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from abductio_core.application.dto import EvidenceItem, RootSpec, SessionConfig, SessionRequest
from abductio_core.application.result import SessionResult, StopReason
from abductio_core.application.use_cases import run_session as rs
from abductio_core.domain.invariants import H_NOA_ID, H_UND_ID, enforce_open_world
from abductio_core.domain.model import Node, RootHypothesis


def _legacy_replay(audit_trace: Iterable[Dict[str, object]]) -> SessionResult:
    ledger: Dict[str, float] = {}
    roots: Dict[str, Dict[str, object]] = {}
    required_root_ids: List[str] = []
    operation_log: List[Dict[str, object]] = []
    stop_reason: Optional[StopReason] = None

    for event in audit_trace:
        et = event.get("event_type")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if et == "SESSION_INITIALIZED":
            required_root_ids = list(payload.get("roots", [])) if isinstance(payload.get("roots"), list) else []
            ledger = dict(payload.get("ledger", {})) if isinstance(payload.get("ledger"), dict) else {}
            for rid in required_root_ids:
                roots.setdefault(str(rid), {"id": str(rid)})
        elif et == "OP_EXECUTED":
            operation_log.append(
                {
                    "op_type": payload.get("op_type"),
                    "target_id": payload.get("target_id"),
                    "credits_before": payload.get("credits_before"),
                    "credits_after": payload.get("credits_after"),
                }
            )
        elif et == "ROOT_SCOPED":
            rid = payload.get("root_id")
            if isinstance(rid, str):
                roots.setdefault(rid, {"id": rid})
                roots[rid]["status"] = "SCOPED"
                roots[rid].setdefault("obligations", {})
        elif et in {"SLOT_DECOMPOSED", "NODE_REFINED_REQUIREMENTS"}:
            slot_node_key = payload.get("slot_node_key") or payload.get("node_key")
            if isinstance(slot_node_key, str) and ":" in slot_node_key:
                parts = slot_node_key.split(":")
                rid = parts[0]
                slot_key = parts[1] if len(parts) > 1 else ""
                roots.setdefault(rid, {"id": rid, "status": "SCOPED", "obligations": {}})
                obligations = roots[rid].setdefault("obligations", {})
                if isinstance(obligations, dict) and slot_key:
                    obligations.setdefault(slot_key, {})
                    if isinstance(obligations[slot_key], dict):
                        obligations[slot_key]["children"] = list(payload.get("children", []))
                        obligations[slot_key]["decomp_type"] = payload.get("type")
                        obligations[slot_key]["coupling"] = payload.get("coupling")
        elif et == "NODE_EVALUATED":
            nk = payload.get("node_key")
            if isinstance(nk, str):
                if ":" in nk:
                    rid = nk.split(":", 1)[0]
                    roots.setdefault(rid, {"id": rid, "status": "SCOPED", "obligations": {}})
        elif et == "DAMPING_APPLIED":
            rid = payload.get("root_id")
            p_new = payload.get("p_new")
            if isinstance(rid, str) and isinstance(p_new, (int, float)):
                ledger[rid] = float(p_new)
                named = [r for r in required_root_ids if r not in {H_NOA_ID, H_UND_ID}]
                if named and (H_NOA_ID in required_root_ids or H_UND_ID in required_root_ids):
                    enforce_open_world(ledger, named)
        elif et == "LOG_LEDGER_NORMALIZED":
            logged = payload.get("ledger")
            if isinstance(logged, dict):
                ledger = {str(k): float(v) for k, v in logged.items() if isinstance(v, (int, float))}
                named = [r for r in required_root_ids if r not in {H_NOA_ID, H_UND_ID}]
                if named and (H_NOA_ID in required_root_ids or H_UND_ID in required_root_ids):
                    enforce_open_world(ledger, named)
        elif et == "NAMED_LEDGER_NORMALIZED":
            logged = payload.get("ledger")
            if isinstance(logged, dict):
                ledger = {str(k): float(v) for k, v in logged.items() if isinstance(v, (int, float))}
        elif et == "STOP_REASON_RECORDED":
            reason = payload.get("stop_reason")
            if isinstance(reason, str):
                try:
                    stop_reason = StopReason(reason)
                except ValueError:
                    stop_reason = None

    named = [r for r in required_root_ids if r not in {H_NOA_ID, H_UND_ID}]
    if named and (H_NOA_ID in required_root_ids or H_UND_ID in required_root_ids):
        enforce_open_world(ledger, named)

    return SessionResult(
        roots={k: dict(v) for k, v in roots.items()},
        ledger=dict(ledger),
        nodes={},
        audit=list(audit_trace),
        stop_reason=stop_reason,
        credits_remaining=0,
        total_credits_spent=len(operation_log),
        operation_log=operation_log,
    )


def _build_request(payload: Dict[str, object]) -> Tuple[SessionRequest, Dict[str, EvidenceItem]]:
    config_payload = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    required_slots = payload.get("required_slots") if isinstance(payload.get("required_slots"), list) else []
    initial_ledger = payload.get("initial_ledger") if isinstance(payload.get("initial_ledger"), dict) else {}
    slot_k_min = payload.get("slot_k_min") if isinstance(payload.get("slot_k_min"), dict) else {}
    slot_initial_p = payload.get("slot_initial_p") if isinstance(payload.get("slot_initial_p"), dict) else {}
    roots_spec = payload.get("roots_spec") if isinstance(payload.get("roots_spec"), list) else []
    root_specs: List[RootSpec] = []
    for entry in roots_spec:
        if not isinstance(entry, dict):
            continue
        root_id = entry.get("root_id")
        if not isinstance(root_id, str) or root_id in {H_NOA_ID, H_UND_ID}:
            continue
        root_specs.append(
            RootSpec(
                root_id=root_id,
                statement=str(entry.get("statement", "")),
                exclusion_clause=str(entry.get("exclusion_clause", "")),
            )
        )
    config = SessionConfig(
        tau=float(config_payload.get("tau", 0.7)),
        epsilon=float(config_payload.get("epsilon", 0.05)),
        gamma_noa=float(config_payload.get("gamma_noa", 0.0)),
        gamma_und=float(config_payload.get("gamma_und", 0.0)),
        alpha=float(config_payload.get("alpha", 0.0)),
        beta=float(config_payload.get("beta", 1.0)),
        W=float(config_payload.get("W", 3.0)),
        lambda_voi=float(config_payload.get("lambda_voi", 0.1)),
        world_mode=str(config_payload.get("world_mode", "open")),
        rho_eval_min=float(config_payload.get("rho_eval_min", 0.5)),
        gamma=float(config_payload.get("gamma", 0.2)),
    )
    evidence_items_payload = payload.get("evidence_items") if isinstance(payload.get("evidence_items"), list) else []
    evidence_index: Dict[str, EvidenceItem] = {}
    for item in evidence_items_payload:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("id") or item.get("evidence_id") or "")
        if not evidence_id:
            continue
        evidence_index[evidence_id] = EvidenceItem(
            id=evidence_id,
            source=str(item.get("source", "")),
            text=str(item.get("text", "")),
            location=item.get("location"),
            metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
        )
    request = SessionRequest(
        scope="replay",
        roots=root_specs,
        config=config,
        credits=0,
        required_slots=required_slots,
        initial_ledger=dict(initial_ledger),
        slot_k_min=dict(slot_k_min),
        slot_initial_p=dict(slot_initial_p),
        evidence_items=list(evidence_index.values()),
        framing=payload.get("framing") if isinstance(payload.get("framing"), str) else None,
    )
    return request, evidence_index


def replay_session(audit_trace: Iterable[Dict[str, object]]) -> SessionResult:
    audit_list = list(audit_trace)
    if not audit_list:
        return _legacy_replay(audit_trace)

    init_payload = None
    for event in audit_list:
        if event.get("event_type") == "SESSION_INITIALIZED" and isinstance(event.get("payload"), dict):
            init_payload = event.get("payload")
            break

    if not init_payload or "config" not in init_payload:
        return _legacy_replay(audit_list)

    request, evidence_index = _build_request(init_payload)
    hypothesis_set = rs._init_hypothesis_set(request)
    required_slot_keys = rs._required_slot_keys(request)
    required_slot_roles = rs._required_slot_roles(request)

    nodes: Dict[str, Node] = {}
    operation_log: List[Dict[str, object]] = []
    stop_reason: Optional[StopReason] = None
    w_applied: Dict[Tuple[str, str], float] = {}
    named_root_ids = [rid for rid in hypothesis_set.roots if rid not in {H_NOA_ID, H_UND_ID}]
    log_ledger: Dict[str, float] = {
        rid: rs._safe_log(float(hypothesis_set.ledger.get(rid, 0.0))) for rid in named_root_ids
    }

    class _NullAuditSink:
        def append(self, _event) -> None:
            return None

    class _NullDeps:
        audit_sink = _NullAuditSink()

    def apply_ledger_update(root: RootHypothesis) -> None:
        weight_cap = float(request.config.W)
        p_base = float(hypothesis_set.ledger.get(root.root_id, 0.0))
        total_delta = 0.0
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            if not node_key:
                continue
            node = nodes.get(node_key)
            if not node or not node.assessed:
                continue
            p = rs._clip(float(node.p), 1e-6, 1.0 - 1e-6)
            ratio = p / 0.5
            w_new = rs._clip(math.log(ratio), -weight_cap, weight_cap)
            key = (root.root_id, slot_key)
            w_prev = w_applied.get(key, 0.0)
            delta = w_new - w_prev
            total_delta += float(delta)
            w_applied[key] = w_new
        beta = float(request.config.beta)
        alpha = float(request.config.alpha)
        log_ledger[root.root_id] = log_ledger.get(root.root_id, rs._safe_log(p_base)) + (beta * total_delta)
        prop_named = rs._normalize_log_ledger(log_ledger) if log_ledger else {}
        p_prop = float(prop_named.get(root.root_id, p_base))
        p_damped = (1.0 - alpha) * p_base + alpha * p_prop

        if prop_named and len(named_root_ids) > 1:
            remaining_prop = 1.0 - p_prop
            remaining_new = 1.0 - p_damped
            if remaining_prop <= 0.0:
                for rid in named_root_ids:
                    if rid != root.root_id:
                        prop_named[rid] = remaining_new / max(1, len(named_root_ids) - 1)
            else:
                scale = remaining_new / remaining_prop
                for rid in named_root_ids:
                    if rid != root.root_id:
                        prop_named[rid] = prop_named.get(rid, 0.0) * scale
            prop_named[root.root_id] = p_damped
        elif prop_named:
            prop_named[root.root_id] = p_damped
        else:
            prop_named = {root.root_id: p_damped}

        for rid in named_root_ids:
            if rid in prop_named:
                hypothesis_set.ledger[rid] = prop_named[rid]
        if request.config.world_mode == "closed":
            total_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
            if total_named > 1.0 and total_named > 0.0:
                for rid in named_root_ids:
                    hypothesis_set.ledger[rid] = hypothesis_set.ledger.get(rid, 0.0) / total_named
        else:
            if H_NOA_ID in hypothesis_set.ledger or H_UND_ID in hypothesis_set.ledger:
                enforce_open_world(hypothesis_set.ledger, named_root_ids)
        for rid in named_root_ids:
            log_ledger[rid] = rs._safe_log(float(hypothesis_set.ledger.get(rid, 0.0)))

    def evaluate_from_event(root: RootHypothesis, node_key: str, payload: Dict[str, object]) -> None:
        node = nodes.get(node_key)
        if node is None:
            node_info = payload.get("node", {}) if isinstance(payload.get("node"), dict) else {}
            node = Node(
                node_key=node_key,
                statement=str(node_info.get("statement", "")),
                role=str(node_info.get("role", "NEC")),
            )
            node.decomp_type = node_info.get("decomp_type")
            node.coupling = node_info.get("coupling")
            nodes[node_key] = node
        outcome = payload.get("outcome", {}) if isinstance(payload.get("outcome"), dict) else {}
        previous_p = float(node.p)
        proposed_p = float(outcome.get("p", previous_p))
        evidence_ids = outcome.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        evidence_ids = [str(item) for item in evidence_ids if isinstance(item, str)]
        missing_ids = [item for item in evidence_ids if item not in evidence_index]
        has_refs = bool(evidence_ids) and not missing_ids
        quotes_valid = True
        if isinstance(outcome.get("quotes"), list):
            for quote in outcome.get("quotes", []):
                if not isinstance(quote, dict):
                    quotes_valid = False
                    continue
                evidence_id = quote.get("evidence_id")
                exact_quote = quote.get("exact_quote")
                if not evidence_id or not exact_quote:
                    quotes_valid = False
                    continue
                item = evidence_index.get(str(evidence_id))
                if item and item.text and str(exact_quote) not in item.text:
                    quotes_valid = False
        if not has_refs:
            delta = max(min(proposed_p - previous_p, 0.05), -0.05)
            proposed_p = previous_p + delta
        node.p = rs._clamp_probability(float(proposed_p))
        node.assessed = True
        rubric = {k: int(outcome[k]) for k in ("A", "B", "C", "D") if k in outcome and str(outcome[k]).isdigit()}
        evidence_quality = outcome.get("evidence_quality")
        if not isinstance(evidence_quality, str):
            evidence_quality = "none" if not evidence_ids else "indirect"
        if not has_refs and rubric:
            rubric["A"] = 0
        if rubric:
            node.k, guardrail = rs._derive_k_from_rubric(rubric)
            if not has_refs and node.k > 0.55:
                node.k = 0.55
            quality_caps = {"weak": 0.35, "indirect": 0.55, "none": 0.35}
            if evidence_quality in quality_caps and node.k > quality_caps[evidence_quality]:
                node.k = quality_caps[evidence_quality]
            if not quotes_valid and node.k > 0.35:
                node.k = 0.35
            assumptions = outcome.get("assumptions")
            if isinstance(assumptions, list) and assumptions and node.k > 0.55:
                node.k = 0.55

        for parent in nodes.values():
            if parent.decomp_type == "AND" and node_key in parent.children:
                aggregated, _details = rs._aggregate_soft_and(parent, nodes)
                parent.p = rs._clamp_probability(float(aggregated))
                parent.assessed = True
            if parent.decomp_type == "OR" and node_key in parent.children:
                children = [nodes[k] for k in parent.children if k in nodes and nodes[k].assessed]
                if not children:
                    parent.p = 0.5
                else:
                    parent.p = max(child.p for child in children)
                parent.assessed = True

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

    for event in audit_list:
        et = event.get("event_type")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if et == "OP_EXECUTED":
            operation_log.append(
                {
                    "op_type": payload.get("op_type"),
                    "target_id": payload.get("target_id"),
                    "credits_before": payload.get("credits_before"),
                    "credits_after": payload.get("credits_after"),
                }
            )
        elif et == "ROOT_DECOMPOSED":
            rid = payload.get("root_id")
            if not isinstance(rid, str):
                continue
            root = hypothesis_set.roots.get(rid)
            if not root:
                root = RootHypothesis(rid, "", "", "")
                hypothesis_set.roots[rid] = root
            decomp = {"ok": bool(payload.get("ok", True))}
            slot_statements = payload.get("slot_statements", {})
            if isinstance(slot_statements, dict):
                for slot_key, statement in slot_statements.items():
                    decomp[f"{slot_key}_statement"] = statement
            rs._decompose_root(
                _NullDeps(),
                root,
                required_slot_keys,
                required_slot_roles,
                decomp,
                (request.slot_k_min or {}).get(rid),
                request.slot_initial_p or {},
                nodes,
            )
        elif et == "NODE_REFINED_REQUIREMENTS":
            node_key = payload.get("node_key")
            if not isinstance(node_key, str):
                continue
            node = nodes.get(node_key)
            if node is None:
                node = Node(node_key=node_key, statement="", role="NEC")
                nodes[node_key] = node
            decomp = {
                "type": payload.get("type"),
                "coupling": payload.get("coupling"),
                "children": [],
            }
            children_spec = payload.get("children_spec")
            if isinstance(children_spec, list):
                for child in children_spec:
                    if not isinstance(child, dict):
                        continue
                    decomp["children"].append(
                        {
                            "child_id": child.get("child_id"),
                            "statement": child.get("statement"),
                            "role": child.get("role", "NEC"),
                            "falsifiable": child.get("falsifiable"),
                            "test_procedure": child.get("test_procedure"),
                            "overlap_with_siblings": child.get("overlap_with_siblings", []),
                        }
                    )
            rs._apply_node_decomposition(_NullDeps(), node_key, decomp, nodes)
        elif et == "NODE_EVALUATED":
            node_key = payload.get("node_key")
            if not isinstance(node_key, str):
                continue
            root_id = node_key.split(":", 1)[0]
            root = hypothesis_set.roots.get(root_id)
            if not root:
                root = RootHypothesis(root_id, "", "", "")
                hypothesis_set.roots[root_id] = root
            evaluate_from_event(root, node_key, payload)
        elif et == "OPEN_WORLD_GAMMA_UPDATED":
            gamma_noa = payload.get("gamma_noa")
            gamma_und = payload.get("gamma_und")
            if isinstance(gamma_noa, (int, float)) and isinstance(gamma_und, (int, float)):
                remaining = 1.0 - float(gamma_noa) - float(gamma_und)
                total_named = sum(hypothesis_set.ledger.get(rid, 0.0) for rid in named_root_ids)
                if total_named > 0.0:
                    for rid in named_root_ids:
                        hypothesis_set.ledger[rid] = hypothesis_set.ledger.get(rid, 0.0) * (remaining / total_named)
                hypothesis_set.ledger[H_NOA_ID] = float(gamma_noa)
                hypothesis_set.ledger[H_UND_ID] = float(gamma_und)
                for rid in named_root_ids:
                    log_ledger[rid] = rs._safe_log(float(hypothesis_set.ledger.get(rid, 0.0)))
        elif et == "ROOT_SCOPED":
            rid = payload.get("root_id")
            if isinstance(rid, str) and rid in hypothesis_set.roots:
                hypothesis_set.roots[rid].status = "SCOPED"
        elif et == "STOP_REASON_RECORDED":
            reason = payload.get("stop_reason")
            if isinstance(reason, str):
                try:
                    stop_reason = StopReason(reason)
                except ValueError:
                    stop_reason = None

    named = [r for r in hypothesis_set.roots if r not in {H_NOA_ID, H_UND_ID}]
    if named and (H_NOA_ID in hypothesis_set.roots or H_UND_ID in hypothesis_set.roots):
        enforce_open_world(hypothesis_set.ledger, named)

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

    return SessionResult(
        roots=roots_view,
        ledger=dict(hypothesis_set.ledger),
        nodes=nodes_view,
        audit=audit_list,
        stop_reason=stop_reason,
        credits_remaining=0,
        total_credits_spent=len(operation_log),
        operation_log=operation_log,
    )
