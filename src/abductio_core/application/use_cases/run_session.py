from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Tuple

from abductio_core.application.dto import EvidenceItem, SessionConfig, SessionRequest
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


def _normalize_quote_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text))
    punctuation_map = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u02bc": "'",
        "\u0060": "'",
        "\u00b4": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2033": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
    normalized_chars: List[str] = []
    for raw_char in value:
        char = punctuation_map.get(raw_char, raw_char)
        category = unicodedata.category(char)
        if category.startswith("C"):
            if char in {"\t", "\n", "\r", "\f", "\v"}:
                normalized_chars.append(" ")
            continue
        normalized_chars.append(char)
    return _normalize_whitespace("".join(normalized_chars))


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


STRICT_NON_DISCRIMINATIVE_EPSILON = 0.02
CONTRADICTION_PENALTY_KAPPA = 0.25
CONTRADICTION_VALIDITY_MIN = 0.50
DEFAULT_DYNAMIC_ABSTENTION_UNRESOLVED_PAIR_WEIGHT = 0.30
DEFAULT_DYNAMIC_ABSTENTION_CONTRADICTION_DENSITY_WEIGHT = 0.25
DEFAULT_DYNAMIC_ABSTENTION_NON_DISCRIMINATIVE_WEIGHT = 0.20
DEFAULT_DYNAMIC_ABSTENTION_MINIMUM = 0.05
DEFAULT_DYNAMIC_ABSTENTION_MAXIMUM = 0.90


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return float(default)
    return float(default)


def _coerce_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return int(default)
    return int(default)


def _infer_reasoning_profile(domain_id: str, scope: str) -> str:
    text = f"{domain_id} {scope}".strip().lower()
    forecasting_markers = (
        "forecast",
        "economy",
        "inflation",
        "gdp",
        "growth",
        "interest rate",
        "unemployment",
        "market",
    )
    causal_markers = (
        "incident",
        "accident",
        "investigation",
        "causal",
        "failure",
        "crash",
        "safety",
        "aaib",
    )
    if any(marker in text for marker in forecasting_markers):
        return "forecasting"
    if any(marker in text for marker in causal_markers):
        return "causal_investigation"
    return "general_reasoning"


def _profile_defaults(profile_name: str) -> Dict[str, object]:
    profile = str(profile_name or "").strip().lower()
    if profile == "forecasting":
        return {
            "reasoning_mode": "explore",
            "strict_contrastive_updates_required": False,
            "min_decomposition_depth_per_slot": 0,
        }
    if profile == "causal_investigation":
        return {
            "reasoning_mode": "certify",
            "strict_contrastive_updates_required": True,
            "min_decomposition_depth_per_slot": 0,
        }
    return {
        "reasoning_mode": "explore",
        "strict_contrastive_updates_required": False,
        "min_decomposition_depth_per_slot": 0,
    }


def _resolve_profile_policy(
    scope: str,
    policy_map: Dict[str, object],
) -> Tuple[Dict[str, object], List[AuditEvent], Dict[str, object]]:
    resolved = dict(policy_map)
    events: List[AuditEvent] = []
    metadata: Dict[str, object] = {}

    auto_select = bool(resolved.get("domain_profile_auto_selection", False))
    domain_id = str(resolved.get("domain_id", "")).strip() or str(scope).strip()
    profile_name = str(resolved.get("reasoning_profile") or resolved.get("profile_name") or "").strip().lower()
    profile_source = str(resolved.get("profile_source", "")).strip().lower()

    min_conf = _clip(_coerce_float(resolved.get("domain_induction_min_confidence"), 0.70), 0.0, 1.0)
    profile_confidence = _clip(
        _coerce_float(
            resolved.get("profile_confidence", resolved.get("domain_profile_confidence", 1.0)),
            1.0,
        ),
        0.0,
        1.0,
    )

    if auto_select and not profile_name:
        profile_name = _infer_reasoning_profile(domain_id, scope)

    if auto_select:
        if profile_confidence >= min_conf:
            profile_source = "induced"
            resolved["reasoning_profile"] = profile_name
            resolved["profile_name"] = profile_name
            events.append(
                AuditEvent(
                    "DOMAIN_PROFILE_INDUCED",
                    {
                        "domain_id": domain_id,
                        "profile_name": profile_name,
                        "profile_confidence": float(profile_confidence),
                        "min_confidence": float(min_conf),
                    },
                )
            )
        else:
            fallback_profile = profile_name or "general_reasoning"
            profile_source = "induction_low_confidence"
            resolved["reasoning_profile"] = fallback_profile
            resolved["profile_name"] = fallback_profile
            resolved.setdefault("reasoning_mode", "explore")
            resolved.setdefault("strict_contrastive_updates_required", False)
            resolved.setdefault("min_decomposition_depth_per_slot", 0)
            resolved.setdefault("allow_policy_tau_relaxation", False)
            # Low-confidence domain induction should default to cautious
            # exploration rather than confident closure.
            resolved.setdefault("frame_adequacy_score", 0.0)
            resolved.setdefault("min_frame_adequacy", 1.0)
            resolved.setdefault("frame_inadequacy_k_cap", 0.55)
            events.append(
                AuditEvent(
                    "DOMAIN_INDUCTION_LOW_CONFIDENCE",
                    {
                        "domain_id": domain_id,
                        "profile_confidence": float(profile_confidence),
                        "min_confidence": float(min_conf),
                        "fallback_profile": fallback_profile,
                    },
                )
            )

    profile_name = str(resolved.get("reasoning_profile") or resolved.get("profile_name") or "").strip().lower()
    if profile_name:
        defaults = _profile_defaults(profile_name)
        for key, value in defaults.items():
            if key == "reasoning_mode" and not auto_select:
                continue
            resolved.setdefault(key, value)
        if not profile_source:
            profile_source = "explicit"
        resolved["reasoning_profile"] = profile_name
        resolved["profile_name"] = profile_name
        resolved["profile_source"] = profile_source
        if (
            not str(resolved.get("reasoning_mode", "")).strip()
            and bool(resolved.get("strict_contrastive_updates_required", False))
        ):
            resolved["reasoning_mode"] = "certify"

        strict_policy = bool(resolved.get("strict_contrastive_updates_required", False))
        min_depth = max(0, _coerce_int(resolved.get("min_decomposition_depth_per_slot"), 0))
        reasoning_mode = str(resolved.get("reasoning_mode", "")).strip().lower()
        events.append(
            AuditEvent(
                "PROFILE_POLICY_APPLIED",
                {
                    "domain_id": domain_id,
                    "profile_name": profile_name,
                    "profile_source": profile_source,
                    "reasoning_mode": reasoning_mode,
                    "strict_contrastive_updates_required": strict_policy,
                    "min_decomposition_depth_per_slot": min_depth,
                },
            )
        )
        metadata = {
            "reasoning_profile": profile_name,
            "reasoning_mode": reasoning_mode,
            "profile_source": profile_source,
            "strict_contrastive_policy": strict_policy,
        }
    elif (
        not str(resolved.get("reasoning_mode", "")).strip()
        and bool(resolved.get("strict_contrastive_updates_required", False))
    ):
        # Conservative fallback: strict contrastive mode implies certify if
        # caller did not set a reasoning mode explicitly.
        resolved["reasoning_mode"] = "certify"

    return resolved, events, metadata


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


def _pair_key(root_a: str, root_b: str) -> str:
    left, right = sorted((str(root_a).strip(), str(root_b).strip()))
    return f"{left}|{right}"


def _pair_catalog(root_ids: List[str]) -> List[str]:
    ordered = sorted([rid for rid in root_ids if rid])
    pairs: List[str] = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            pairs.append(_pair_key(left, right))
    return pairs


def _pair_count_for_root_count(root_count: int) -> int:
    count = int(root_count)
    if count < 2:
        return 0
    return (count * (count - 1)) // 2


def _max_root_count_for_pair_budget(root_count: int, pair_budget: int) -> int:
    available = max(0, int(root_count))
    budget = max(0, int(pair_budget))
    if available < 2 or budget < 1:
        return 0
    candidate = available
    while candidate >= 2 and _pair_count_for_root_count(candidate) > budget:
        candidate -= 1
    return candidate if candidate >= 2 else 0


def _rank_pairs_by_mass(pair_keys: List[str], ledger: Dict[str, float]) -> List[str]:
    def _pair_priority(pair_key: str) -> Tuple[float, float, str]:
        left, right = pair_key.split("|", 1) if "|" in pair_key else (pair_key, "")
        left_mass = max(0.0, float(ledger.get(left, 0.0)))
        right_mass = max(0.0, float(ledger.get(right, 0.0)))
        return (-max(left_mass, right_mass), -(left_mass + right_mass), pair_key)

    ranked = [str(pair).strip() for pair in pair_keys if str(pair).strip()]
    ranked.sort(key=_pair_priority)
    return ranked


def _limit_pairs_by_budget(
    pair_keys: List[str],
    *,
    pair_budget: int,
    ledger: Dict[str, float],
) -> List[str]:
    budget = max(0, int(pair_budget))
    unique_pairs: List[str] = []
    seen: set[str] = set()
    for pair in pair_keys:
        token = str(pair).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        unique_pairs.append(token)
    if not unique_pairs or budget <= 0:
        return []
    if budget >= len(unique_pairs):
        return list(unique_pairs)
    ranked = _rank_pairs_by_mass(unique_pairs, ledger)
    return ranked[:budget]


def _normalize_pairwise_overlaps(
    raw: object,
    known_root_ids: set[str],
) -> Dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("mece_certificate.pairwise_overlaps must be an object")
    normalized: Dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError("pairwise_overlaps keys must be strings formatted as ROOT_A|ROOT_B")
        parts = [part.strip() for part in key.split("|")]
        if len(parts) != 2 or not parts[0] or not parts[1] or parts[0] == parts[1]:
            raise ValueError(f"invalid pairwise_overlaps key: {key!r}")
        if parts[0] not in known_root_ids or parts[1] not in known_root_ids:
            raise ValueError(f"pairwise_overlaps key references unknown root id: {key!r}")
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pairwise_overlaps score must be numeric for pair {key!r}") from exc
        if not (0.0 <= score <= 2.0):
            raise ValueError(f"pairwise_overlaps score must be within [0,2] for pair {key!r}")
        canonical = _pair_key(parts[0], parts[1])
        existing = normalized.get(canonical)
        if existing is not None and abs(existing - score) > 1e-12:
            raise ValueError(f"conflicting pairwise_overlaps values for pair {canonical!r}")
        normalized[canonical] = score
    return normalized


def _normalize_pairwise_discriminators(
    raw: object,
    known_root_ids: set[str],
) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("mece_certificate.pairwise_discriminators must be an object")
    normalized: Dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError("pairwise_discriminators keys must be strings formatted as ROOT_A|ROOT_B")
        parts = [part.strip() for part in key.split("|")]
        if len(parts) != 2 or not parts[0] or not parts[1] or parts[0] == parts[1]:
            raise ValueError(f"invalid pairwise_discriminators key: {key!r}")
        if parts[0] not in known_root_ids or parts[1] not in known_root_ids:
            raise ValueError(f"pairwise_discriminators key references unknown root id: {key!r}")
        text = _normalize_whitespace(str(value))
        canonical = _pair_key(parts[0], parts[1])
        existing = normalized.get(canonical)
        if existing is not None and existing != text:
            raise ValueError(f"conflicting pairwise_discriminators values for pair {canonical!r}")
        normalized[canonical] = text
    return normalized


def _assess_mece_certificate(request: SessionRequest) -> Dict[str, object]:
    root_ids = [root.root_id for root in request.roots if root.root_id]
    pair_catalog = _pair_catalog(root_ids)
    known_root_ids = set(root_ids)
    cert_raw = request.mece_certificate
    if cert_raw is None:
        cert: Dict[str, object] = {}
    elif isinstance(cert_raw, dict):
        cert = dict(cert_raw)
    else:
        raise ValueError("mece_certificate must be an object when provided")

    strict = bool(request.strict_mece) if request.strict_mece is not None else bool(cert.get("strict", False))
    threshold_raw = request.max_pair_overlap if request.max_pair_overlap is not None else cert.get("max_pair_overlap", 1.0)
    try:
        max_pair_overlap = float(threshold_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_pair_overlap must be numeric") from exc
    if not (0.0 <= max_pair_overlap <= 2.0):
        raise ValueError("max_pair_overlap must be within [0,2]")

    pairwise_overlaps = _normalize_pairwise_overlaps(cert.get("pairwise_overlaps"), known_root_ids)
    pairwise_discriminators = _normalize_pairwise_discriminators(cert.get("pairwise_discriminators"), known_root_ids)

    issues: List[Dict[str, object]] = []
    if strict:
        for pair in pair_catalog:
            if pair not in pairwise_overlaps:
                issues.append({"code": "missing_pairwise_overlap_score", "pair": pair})
            text = pairwise_discriminators.get(pair, "")
            if not text:
                issues.append({"code": "missing_pairwise_discriminator", "pair": pair})

    for pair, score in sorted(pairwise_overlaps.items()):
        if score > max_pair_overlap:
            issues.append(
                {
                    "code": "pair_overlap_exceeds_threshold",
                    "pair": pair,
                    "score": score,
                    "max_pair_overlap": max_pair_overlap,
                }
            )

    status = "FAILED" if issues else "PASSED"
    return {
        "status": status,
        "strict": strict,
        "max_pair_overlap": max_pair_overlap,
        "pair_count": len(pair_catalog),
        "pairwise_overlap_covered": len(pairwise_overlaps),
        "pairwise_discriminator_covered": len(pairwise_discriminators),
        "pairwise_overlaps": pairwise_overlaps,
        "pairwise_discriminators": pairwise_discriminators,
        "issues": issues,
    }


def _normalize_contender_space_mode(raw_mode: object) -> str:
    token = _normalize_whitespace(str(raw_mode or "")).lower()
    if not token:
        return "singleton_roots"
    if token in {"singleton_roots", "singleton_root", "singleton", "singletons", "single_root"}:
        return "singleton_roots"
    if token in {"compositional_stories", "compositional_story", "compositional", "stories", "story"}:
        return "compositional_stories"
    return ""


def _coerce_story_components(raw_components: object) -> Optional[List[str]]:
    if isinstance(raw_components, str):
        parts = [part.strip() for part in raw_components.split(",")]
    elif isinstance(raw_components, (list, tuple, set)):
        parts = [str(part).strip() for part in raw_components]
    else:
        return None

    cleaned: List[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        cleaned.append(part)
    return cleaned


def _composite_story_root_id(component_ids: Tuple[str, ...]) -> str:
    return "CS__" + "__".join(component_ids)


def _expand_compositional_story_roots(
    hypothesis_set: HypothesisSet,
    max_cardinality: int,
) -> Dict[str, List[str]]:
    named_root_ids = sorted(
        [
            root_id
            for root_id in hypothesis_set.roots
            if root_id not in {H_NOA_ID, H_UND_ID}
        ]
    )
    components_by_root: Dict[str, List[str]] = {root_id: [root_id] for root_id in named_root_ids}
    if len(named_root_ids) < 2:
        return components_by_root

    capped_cardinality = max(1, min(int(max_cardinality), len(named_root_ids)))
    if capped_cardinality < 2:
        return components_by_root

    for cardinality in range(2, capped_cardinality + 1):
        for component_ids in combinations(named_root_ids, cardinality):
            story_id = _composite_story_root_id(component_ids)
            if story_id in hypothesis_set.roots:
                components_by_root.setdefault(story_id, list(component_ids))
                continue
            story_statements = [hypothesis_set.roots[root_id].statement for root_id in component_ids]
            statement = "Composite story: " + " + ".join(story_statements)
            exclusion_clause = f"Composite of {', '.join(component_ids)}"
            hypothesis_set.roots[story_id] = RootHypothesis(
                root_id=story_id,
                statement=statement,
                exclusion_clause=exclusion_clause,
                canonical_id=canonical_id_for_statement(statement),
            )
            hypothesis_set.ledger[story_id] = 0.0
            components_by_root[story_id] = list(component_ids)

    all_named_root_ids = sorted(
        [
            root_id
            for root_id in hypothesis_set.roots
            if root_id not in {H_NOA_ID, H_UND_ID}
        ]
    )
    total_named_mass = sum(max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in all_named_root_ids)
    if total_named_mass <= 1e-12:
        total_named_mass = max(
            0.0,
            1.0 - float(hypothesis_set.ledger.get(H_NOA_ID, 0.0)) - float(hypothesis_set.ledger.get(H_UND_ID, 0.0)),
        )
    if all_named_root_ids:
        per_root = total_named_mass / float(len(all_named_root_ids))
        for root_id in all_named_root_ids:
            hypothesis_set.ledger[root_id] = per_root

    return components_by_root


def _ensure_singleton_story_roots(
    hypothesis_set: HypothesisSet,
) -> Dict[str, List[str]]:
    base_root_ids = sorted(
        [
            root_id
            for root_id in hypothesis_set.roots
            if root_id not in {H_NOA_ID, H_UND_ID} and not str(root_id).startswith("CS__")
        ]
    )
    if not base_root_ids:
        return {}

    components_by_story: Dict[str, List[str]] = {}
    for base_root_id in base_root_ids:
        story_id = _composite_story_root_id((base_root_id,))
        if story_id not in hypothesis_set.roots:
            base_root = hypothesis_set.roots.get(base_root_id)
            base_statement = base_root.statement if base_root else base_root_id
            statement = f"Story: {base_statement}"
            exclusion_clause = f"Singleton story for {base_root_id}"
            hypothesis_set.roots[story_id] = RootHypothesis(
                root_id=story_id,
                statement=statement,
                exclusion_clause=exclusion_clause,
                canonical_id=canonical_id_for_statement(statement),
            )
            hypothesis_set.ledger[story_id] = 0.0
        components_by_story[story_id] = [base_root_id]
    return components_by_story


def _assess_contender_space(named_root_ids: List[str], policy_map: Dict[str, object]) -> Dict[str, object]:
    root_ids = sorted({str(root_id).strip() for root_id in named_root_ids if str(root_id).strip()})
    raw_mode = policy_map.get("contender_space_mode", "")
    explicit_mode = bool(str(raw_mode).strip())
    normalized_mode = _normalize_contender_space_mode(raw_mode)
    mode = normalized_mode or "singleton_roots"
    max_story_cardinality_limit = max(1, _coerce_int(policy_map.get("contender_story_max_cardinality"), 2))
    auto_expanded = bool(policy_map.get("contender_story_auto_expanded", False))

    issues: List[Dict[str, object]] = []
    if explicit_mode and not normalized_mode:
        issues.append(
            {
                "code": "invalid_contender_space_mode",
                "provided": str(raw_mode),
                "allowed_modes": ["singleton_roots", "compositional_stories"],
            }
        )

    provided_components: Dict[str, List[str]] = {}
    raw_components = policy_map.get("contender_story_components")
    if raw_components is not None:
        if not isinstance(raw_components, dict):
            issues.append(
                {
                    "code": "invalid_contender_story_components_type",
                    "expected_type": "object",
                    "actual_type": type(raw_components).__name__,
                }
            )
        else:
            for raw_root_id, raw_list in raw_components.items():
                root_id = str(raw_root_id).strip()
                if not root_id:
                    issues.append({"code": "invalid_story_component_root_id"})
                    continue
                components = _coerce_story_components(raw_list)
                if components is None:
                    issues.append(
                        {
                            "code": "invalid_story_component_list_type",
                            "root_id": root_id,
                            "actual_type": type(raw_list).__name__,
                        }
                    )
                    continue
                provided_components[root_id] = components

    known_root_ids = set(root_ids)
    for root_id in sorted(provided_components.keys()):
        if root_id not in known_root_ids:
            issues.append({"code": "unknown_root_in_story_components", "root_id": root_id})

    components_by_root: Dict[str, List[str]] = {}
    for root_id in root_ids:
        components = list(provided_components.get(root_id, []))
        if not components and mode == "singleton_roots":
            components = [root_id]
        components_by_root[root_id] = components

    cardinality_by_root = {root_id: len(components) for root_id, components in components_by_root.items()}
    multi_factor_story_count = sum(1 for count in cardinality_by_root.values() if count >= 2)
    for root_id, cardinality in sorted(cardinality_by_root.items()):
        if int(cardinality) > int(max_story_cardinality_limit):
            issues.append(
                {
                    "code": "story_cardinality_exceeds_limit",
                    "root_id": root_id,
                    "cardinality": int(cardinality),
                    "max_cardinality": int(max_story_cardinality_limit),
                }
            )

    if mode == "singleton_roots":
        for root_id in root_ids:
            count = int(cardinality_by_root.get(root_id, 0))
            if count != 1:
                issues.append(
                    {
                        "code": "singleton_mode_requires_unary_components",
                        "root_id": root_id,
                        "cardinality": count,
                    }
                )
    elif mode == "compositional_stories":
        for root_id in root_ids:
            if int(cardinality_by_root.get(root_id, 0)) <= 0:
                issues.append({"code": "missing_story_components", "root_id": root_id})
        if root_ids and multi_factor_story_count <= 0:
            issues.append({"code": "compositional_mode_requires_multi_factor_story"})

    signature_to_roots: Dict[Tuple[str, ...], List[str]] = {}
    for root_id in root_ids:
        components = components_by_root.get(root_id, [])
        if not components:
            continue
        signature = tuple(sorted(components))
        signature_to_roots.setdefault(signature, []).append(root_id)
    for signature, roots in sorted(signature_to_roots.items(), key=lambda row: row[0]):
        if len(roots) >= 2:
            issues.append(
                {
                    "code": "duplicate_story_signature",
                    "roots": sorted(roots),
                    "signature": list(signature),
                }
            )

    status = "FAILED" if issues else "PASSED"
    return {
        "status": status,
        "mode": mode,
        "explicit_mode": explicit_mode,
        "root_count": len(root_ids),
        "auto_expanded": bool(auto_expanded),
        "max_story_cardinality_limit": int(max_story_cardinality_limit),
        "cardinality_by_root": cardinality_by_root,
        "story_components_by_root": components_by_root,
        "max_story_cardinality": max(cardinality_by_root.values(), default=0),
        "multi_factor_story_count": int(multi_factor_story_count),
        "issues": issues,
    }


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
    if request.strict_mece is not None and not isinstance(request.strict_mece, bool):
        raise ValueError("strict_mece must be boolean when provided")
    if request.max_pair_overlap is not None:
        try:
            threshold = float(request.max_pair_overlap)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_pair_overlap must be numeric") from exc
        if not (0.0 <= threshold <= 2.0):
            raise ValueError("max_pair_overlap must be within [0,2]")
    if request.mece_certificate is not None and not isinstance(request.mece_certificate, dict):
        raise ValueError("mece_certificate must be an object when provided")
    if request.policy is not None and not isinstance(request.policy, dict):
        raise ValueError("policy must be an object when provided")
    # Parse and normalize MECE fields early so malformed pair keys fail fast.
    _assess_mece_certificate(request)


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


def _aggregate_soft_or(node: Node, nodes: Dict[str, Node]) -> Tuple[float, Dict[str, object]]:
    assessed = [nodes[k] for k in node.children if k in nodes and nodes[k].assessed]
    if not assessed:
        return 0.5, {"p_max": 0.5, "decisive_child": None}
    decisive = sorted(assessed, key=lambda child: (-float(child.p), child.node_key))[0]
    return float(decisive.p), {"p_max": float(decisive.p), "decisive_child": decisive.node_key}


def _propagate_parent_k(node: Node, nodes: Dict[str, Node]) -> Tuple[float, Dict[str, object]]:
    children = [nodes[k] for k in sorted(node.children) if k in nodes]
    assessed_children = [child for child in children if child.assessed]
    details: Dict[str, object] = {
        "node_key": node.node_key,
        "rule": "NO_CHILDREN",
        "decomp_type": node.decomp_type,
        "children_total": len(children),
        "children_assessed": len(assessed_children),
        "decisive_child": None,
        "unscoped_child_present": False,
        "unscoped_cap_applied": False,
        "guardrail_signal": False,
        "guardrail_cap_applied": False,
    }
    if not children:
        return float(node.k), details

    decisive: Optional[Node] = None
    if node.decomp_type == "AND":
        decisive = sorted(children, key=lambda child: (float(child.k), child.node_key))[0]
        propagated_k = float(decisive.k)
        details["rule"] = "AND_MIN_K"
    elif node.decomp_type == "OR":
        decisive = sorted(children, key=lambda child: (-float(child.p), child.node_key))[0]
        propagated_k = float(decisive.k)
        details["rule"] = "OR_MAX_P_TIEBREAK"
    else:
        details["rule"] = "UNSUPPORTED"
        return float(node.k), details

    details["decisive_child"] = decisive.node_key if decisive else None

    unscoped_child_present = any(str(child.role).upper() == "UNSCOPED" for child in children)
    details["unscoped_child_present"] = unscoped_child_present
    if unscoped_child_present and propagated_k > 0.40:
        propagated_k = 0.40
        details["unscoped_cap_applied"] = True

    if details["rule"] == "AND_MIN_K":
        guardrail_signal = any(bool(getattr(child, "guardrail_applied", False)) for child in children)
    else:
        guardrail_signal = bool(getattr(decisive, "guardrail_applied", False))
    details["guardrail_signal"] = guardrail_signal
    if guardrail_signal and propagated_k > 0.55:
        propagated_k = 0.55
        details["guardrail_cap_applied"] = True

    return _clip(float(propagated_k), 0.0, 1.0), details


def _propagate_parent_updates(changed_node_key: str, nodes: Dict[str, Node]) -> List[AuditEvent]:
    queue: List[str] = [changed_node_key]
    queued = {changed_node_key}
    events: List[AuditEvent] = []

    while queue:
        child_key = queue.pop(0)
        for parent in sorted(nodes.values(), key=lambda row: row.node_key):
            if child_key not in parent.children:
                continue
            if parent.decomp_type not in {"AND", "OR"}:
                continue

            previous_p = float(parent.p)
            previous_k = float(parent.k)

            if parent.decomp_type == "AND":
                aggregated, details = _aggregate_soft_and(parent, nodes)
                parent.p = _clamp_probability(float(aggregated))
                parent.assessed = True
                events.append(
                    AuditEvent("SOFT_AND_COMPUTED", {"node_key": parent.node_key, **details, "m": parent.p})
                )
            else:
                aggregated, details = _aggregate_soft_or(parent, nodes)
                parent.p = _clamp_probability(float(aggregated))
                parent.assessed = True
                events.append(
                    AuditEvent(
                        "SOFT_OR_COMPUTED",
                        {"node_key": parent.node_key, "m": parent.p, "decisive_child": details["decisive_child"]},
                    )
                )

            parent.k, k_details = _propagate_parent_k(parent, nodes)
            events.append(
                AuditEvent(
                    "PARENT_K_PROPAGATED",
                    {
                        "node_key": parent.node_key,
                        "k_parent": float(parent.k),
                        **k_details,
                    },
                )
            )

            changed = abs(parent.p - previous_p) > 1e-12 or abs(parent.k - previous_k) > 1e-12
            if changed and parent.node_key not in queued:
                queue.append(parent.node_key)
                queued.add(parent.node_key)

    return events


def _recompute_root_confidence(
    root: RootHypothesis,
    required_slot_keys: List[str],
    required_slot_roles: Dict[str, str],
    nodes: Dict[str, Node],
) -> None:
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
        root.k_root = min(float(node.k) for node in slot_nodes)


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
    if node.decomp_type is not None or node.children or float(node.k) >= float(tau) or credits_left <= 0:
        return False
    depth = node.node_key.count(":") + 1
    # Root-slot decomposition may happen pre-assessment. Deeper recursive
    # decomposition requires at least one assessment to avoid decomposition-only
    # credit exhaustion.
    if depth <= 2:
        return True
    return bool(node.assessed)


def _decomposer_can_decompose(decomposer: object | None, target_id: str) -> bool:
    if decomposer is None:
        return True
    probe = getattr(decomposer, "has_decomposition", None)
    if not callable(probe):
        return True
    try:
        return bool(probe(target_id))
    except Exception:
        return True


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


def _subtree_depth(node_key: str, nodes: Dict[str, Node]) -> int:
    node = nodes.get(node_key)
    if not node or not node.children:
        return 0
    return 1 + max(_subtree_depth(child_key, nodes) for child_key in node.children if child_key in nodes)


def _frontier_confident(
    frontier: List[RootHypothesis],
    required_slot_keys: List[str],
    nodes: Dict[str, Node],
    tau: float,
    min_decomposition_depth: int = 0,
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
            if int(min_decomposition_depth) > 0 and _subtree_depth(node_key, nodes) < int(min_decomposition_depth):
                return False
    return True


def _legal_next_for_root(
    root: RootHypothesis,
    required_slot_keys: List[str],
    tau: float,
    nodes: Dict[str, Node],
    credits_left: int,
    decomposer: object | None = None,
    min_decomposition_depth: int = 0,
) -> Optional[Tuple[str, str]]:
    if root.status == "UNSCOPED":
        return ("DECOMPOSE", root.root_id)
    if any(k not in root.obligations for k in required_slot_keys):
        return ("DECOMPOSE", root.root_id)

    order = _slot_order_map(required_slot_keys)
    ordered_slots: List[Tuple[int, Node]] = []
    for slot_key in required_slot_keys:
        node_key = root.obligations.get(slot_key)
        if not node_key:
            continue
        slot = nodes.get(node_key)
        if not slot:
            continue
        ordered_slots.append((order.get(slot_key, 10_000), slot))
    ordered_slots.sort(key=lambda item: (float(item[1].k), item[0]))
    if not ordered_slots:
        return None

    # Evaluate slot requirements first so direct slot evidence is always
    # consumed before child-level exploration.
    for _, slot in ordered_slots:
        if not slot.assessed:
            return ("EVALUATE", slot.node_key)

    # If a slot remains below confidence threshold, continue evaluating
    # unresolved descendants before further decomposition.
    for _, slot in ordered_slots:
        child_key = _select_unassessed_in_subtree(slot, nodes)
        if child_key and float(slot.k) < float(tau):
            return ("EVALUATE", child_key)

    # Once all required slots have at least one assessment, allow decomposition
    # for low-confidence assessed nodes.
    for _, slot in ordered_slots:
        if int(min_decomposition_depth) > 0:
            depth = _subtree_depth(slot.node_key, nodes)
            if depth < int(min_decomposition_depth) and _decomposer_can_decompose(decomposer, slot.node_key):
                return ("DECOMPOSE", slot.node_key)
        if _node_needs_decomposition(slot, tau, credits_left) and _decomposer_can_decompose(decomposer, slot.node_key):
            return ("DECOMPOSE", slot.node_key)
        child_decompose = _select_decompose_in_subtree(slot, nodes, tau, credits_left)
        if child_decompose and _decomposer_can_decompose(decomposer, child_decompose):
            return ("DECOMPOSE", child_decompose)

    return None


def run_session(request: SessionRequest, deps: RunSessionDeps) -> SessionResult:
    _validate_request(request)

    hypothesis_set = _init_hypothesis_set(request)
    required_slot_keys = _required_slot_keys(request)
    required_slot_roles = _required_slot_roles(request)
    evidence_index = _evidence_index(request)
    evidence_packet_hash = _hash_evidence_packet(evidence_index)
    policy_map = dict(request.policy) if isinstance(request.policy, dict) else {}
    policy_map, profile_policy_events, profile_metadata = _resolve_profile_policy(request.scope, policy_map)
    compositional_story_auto_expand = bool(policy_map.get("compositional_story_auto_expand", False))
    contender_story_max_cardinality = max(1, _coerce_int(policy_map.get("contender_story_max_cardinality"), 2))
    contender_space_mode = _normalize_contender_space_mode(policy_map.get("contender_space_mode", ""))
    singleton_stories_explicit_contenders = bool(policy_map.get("singleton_stories_explicit_contenders", False))
    compositional_story_space_built = False
    compositional_story_space_roots: List[str] = []
    if compositional_story_auto_expand and contender_space_mode == "compositional_stories":
        auto_components = _expand_compositional_story_roots(
            hypothesis_set,
            max_cardinality=contender_story_max_cardinality,
        )
        if auto_components:
            merged_components: Dict[str, object] = {}
            existing_components = policy_map.get("contender_story_components")
            if isinstance(existing_components, dict):
                merged_components.update(existing_components)
            for root_id, components in auto_components.items():
                merged_components.setdefault(root_id, list(components))
            policy_map["contender_story_components"] = merged_components
            policy_map["contender_story_auto_expanded"] = True
            compositional_story_space_built = True
    if singleton_stories_explicit_contenders and contender_space_mode == "compositional_stories":
        singleton_components = _ensure_singleton_story_roots(hypothesis_set)
        if singleton_components:
            merged_components: Dict[str, object] = {}
            existing_components = policy_map.get("contender_story_components")
            if isinstance(existing_components, dict):
                merged_components.update(existing_components)
            for root_id, components in singleton_components.items():
                merged_components[root_id] = list(components)
            policy_map["contender_story_components"] = merged_components
            compositional_story_space_built = True
    if compositional_story_space_built:
        compositional_story_space_roots = sorted(
            [root_id for root_id in hypothesis_set.roots if root_id not in {H_NOA_ID, H_UND_ID}]
        )

    frame_adequacy_score = _coerce_float(policy_map.get("frame_adequacy_score"), float("nan"))
    min_frame_adequacy = _coerce_float(policy_map.get("min_frame_adequacy"), float("nan"))
    frame_inadequacy_k_cap = _coerce_float(policy_map.get("frame_inadequacy_k_cap"), float("nan"))
    frame_inadequacy_reserve = policy_map.get("frame_inadequacy_reserve")
    frame_inadequate = (
        not math.isnan(frame_adequacy_score)
        and not math.isnan(min_frame_adequacy)
        and frame_adequacy_score < min_frame_adequacy
    )

    reasoning_profile = str(policy_map.get("reasoning_profile", "")).strip().lower()
    historical_calibration_status = str(policy_map.get("historical_calibration_status", "")).strip().lower()
    forecasting_confidence_cap = _coerce_float(policy_map.get("forecasting_confidence_cap"), float("nan"))
    forecasting_cap_active = (
        reasoning_profile == "forecasting"
        and historical_calibration_status == "unvalidated"
        and not math.isnan(forecasting_confidence_cap)
    )
    reasoning_mode_raw = str(policy_map.get("reasoning_mode", "")).strip().lower()
    reasoning_mode = reasoning_mode_raw if reasoning_mode_raw in {"certify", "explore"} else ""
    allow_policy_tau_relaxation = bool(policy_map.get("allow_policy_tau_relaxation", True))

    strict_contrastive_updates_required = bool(policy_map.get("strict_contrastive_updates_required", False))
    unresolved_contradiction_pressure = _clip(
        _coerce_float(policy_map.get("unresolved_contradiction_pressure"), 0.0), 0.0, 1.0
    )
    active_discriminator_coverage_ratio = _clip(
        _coerce_float(policy_map.get("active_discriminator_coverage_ratio"), 1.0), 0.0, 1.0
    )
    min_discriminator_coverage_ratio = _clip(
        _coerce_float(policy_map.get("min_discriminator_coverage_ratio"), 0.0), 0.0, 1.0
    )
    dynamic_abstention_mass_enabled = bool(policy_map.get("dynamic_abstention_mass_enabled", True))
    dynamic_abstention_unresolved_pair_weight = _clip(
        _coerce_float(
            policy_map.get("dynamic_abstention_unresolved_pair_weight"),
            DEFAULT_DYNAMIC_ABSTENTION_UNRESOLVED_PAIR_WEIGHT,
        ),
        0.0,
        1.0,
    )
    dynamic_abstention_contradiction_density_weight = _clip(
        _coerce_float(
            policy_map.get("dynamic_abstention_contradiction_density_weight"),
            DEFAULT_DYNAMIC_ABSTENTION_CONTRADICTION_DENSITY_WEIGHT,
        ),
        0.0,
        1.0,
    )
    dynamic_abstention_non_discriminative_weight = _clip(
        _coerce_float(
            policy_map.get("dynamic_abstention_non_discriminative_weight"),
            DEFAULT_DYNAMIC_ABSTENTION_NON_DISCRIMINATIVE_WEIGHT,
        ),
        0.0,
        1.0,
    )
    dynamic_abstention_v2_enabled = bool(policy_map.get("dynamic_abstention_v2_enabled", False))
    dynamic_abstention_frame_adequacy_weight = _clip(
        _coerce_float(policy_map.get("dynamic_abstention_frame_adequacy_weight"), 0.0),
        0.0,
        1.0,
    )
    fixed_abstention_dominant_floor_enabled = bool(
        policy_map.get("fixed_abstention_dominant_floor_enabled", True)
    )
    dynamic_abstention_mass_minimum = _clip(
        _coerce_float(policy_map.get("dynamic_abstention_mass_minimum"), DEFAULT_DYNAMIC_ABSTENTION_MINIMUM),
        0.0,
        0.99,
    )
    dynamic_abstention_mass_maximum = _clip(
        _coerce_float(policy_map.get("dynamic_abstention_mass_maximum"), DEFAULT_DYNAMIC_ABSTENTION_MAXIMUM),
        0.0,
        0.99,
    )
    if dynamic_abstention_mass_maximum < dynamic_abstention_mass_minimum:
        dynamic_abstention_mass_maximum = dynamic_abstention_mass_minimum

    evidence_dependency_overlap_threshold = _clip(
        _coerce_float(policy_map.get("evidence_dependency_overlap_threshold"), float("nan")), 0.0, 1.0
    )
    dependency_penalty_k_cap = _coerce_float(policy_map.get("dependency_penalty_k_cap"), float("nan"))
    root_support_sources = policy_map.get("root_support_sources")
    if not isinstance(root_support_sources, dict):
        root_support_sources = {}

    assumption_overlap_k_cap = _coerce_float(policy_map.get("assumption_overlap_k_cap"), float("nan"))
    slot_assumptions_by_root = policy_map.get("slot_assumptions_by_root")
    if not isinstance(slot_assumptions_by_root, dict):
        slot_assumptions_by_root = {}

    min_winner_margin = _clip(_coerce_float(policy_map.get("min_winner_margin"), 0.0), 0.0, 1.0)
    min_decomposition_depth_per_slot = max(0, _coerce_int(policy_map.get("min_decomposition_depth_per_slot"), 0))
    decision_contract_enabled = bool(policy_map.get("decision_contract_enabled", False))
    dual_outputs_enabled = bool(policy_map.get("dual_outputs_enabled", False))
    selection_output_required = bool(policy_map.get("selection_output_required", False))
    certification_output_allows_abstention = bool(policy_map.get("certification_output_allows_abstention", False))
    decision_min_pairwise_coverage_ratio = _clip(
        _coerce_float(policy_map.get("decision_min_pairwise_coverage_ratio"), min_discriminator_coverage_ratio),
        0.0,
        1.0,
    )
    decision_min_winner_margin = _clip(
        _coerce_float(policy_map.get("decision_min_winner_margin"), min_winner_margin),
        0.0,
        1.0,
    )
    decision_active_set_enabled = bool(policy_map.get("decision_active_set_enabled", False))
    decision_active_set_size = max(0, _coerce_int(policy_map.get("decision_active_set_size"), 2))
    decision_active_set_mass_ratio = _clip(
        _coerce_float(policy_map.get("decision_active_set_mass_ratio"), 0.0),
        0.0,
        1.0,
    )
    closure_active_set_adjudication_required = bool(policy_map.get("closure_active_set_adjudication_required", False))
    closure_active_set_size = max(
        0,
        _coerce_int(
            policy_map.get("closure_active_set_size"),
            decision_active_set_size if decision_active_set_size > 0 else 2,
        ),
    )
    closure_active_set_mass_ratio = _clip(
        _coerce_float(policy_map.get("closure_active_set_mass_ratio"), decision_active_set_mass_ratio),
        0.0,
        1.0,
    )
    closure_min_pairwise_coverage_ratio = _clip(
        _coerce_float(policy_map.get("closure_min_pairwise_coverage_ratio"), min_discriminator_coverage_ratio),
        0.0,
        1.0,
    )
    pair_adjudication_queue_enabled = bool(policy_map.get("pair_adjudication_queue_enabled", False))
    pair_adjudication_scope = str(policy_map.get("pair_adjudication_scope", "active_set")).strip().lower()
    if pair_adjudication_scope not in {"active_set", "global"}:
        pair_adjudication_scope = "active_set"
    pair_adjudication_active_set_size = max(
        0,
        _coerce_int(
            policy_map.get("pair_adjudication_active_set_size"),
            closure_active_set_size if closure_active_set_size > 0 else 2,
        ),
    )
    pair_adjudication_active_set_mass_ratio = _clip(
        _coerce_float(
            policy_map.get("pair_adjudication_active_set_mass_ratio"),
            closure_active_set_mass_ratio,
        ),
        0.0,
        1.0,
    )
    pair_adjudication_active_set_lock_enabled = bool(
        policy_map.get("pair_adjudication_active_set_lock_enabled", True)
    )
    pair_adjudication_balance_targets = bool(policy_map.get("pair_adjudication_balance_targets", True))
    pair_adjudication_min_targets_per_side = max(
        1,
        _coerce_int(policy_map.get("pair_adjudication_min_targets_per_side"), 1),
    )
    pair_adjudication_bootstrap_missing_side = bool(
        policy_map.get("pair_adjudication_bootstrap_missing_side", True)
    )
    pair_adjudication_budget_feasible_enabled = bool(
        policy_map.get("pair_adjudication_budget_feasible_enabled", True)
    )
    pair_adjudication_pair_budget = max(
        0,
        _coerce_int(
            policy_map.get("pair_adjudication_pair_budget"),
            int(request.credits),
        ),
    )
    decision_require_loser_falsification = bool(policy_map.get("decision_require_loser_falsification", False))
    decision_require_counterevidence_probe = bool(policy_map.get("decision_require_counterevidence_probe", False))
    typed_discriminator_evidence_required = bool(policy_map.get("typed_discriminator_evidence_required", False))
    typed_absence_evidence_enabled = bool(policy_map.get("typed_absence_evidence_enabled", False))
    inference_weighting_calibration_enabled = bool(policy_map.get("inference_weighting_calibration_enabled", False))
    profile_inference_multipliers_raw = policy_map.get("profile_inference_multipliers")
    profile_inference_multipliers: Dict[str, float] = {}
    if isinstance(profile_inference_multipliers_raw, dict):
        for raw_source, raw_multiplier in profile_inference_multipliers_raw.items():
            source = str(raw_source).strip()
            if not source:
                continue
            profile_inference_multipliers[source] = _clip(_coerce_float(raw_multiplier, 1.0), 0.0, 1.0)

    compositional_regularization_enabled = bool(policy_map.get("compositional_regularization_enabled", False))
    compositional_complexity_penalty_lambda = max(
        0.0,
        _coerce_float(policy_map.get("compositional_complexity_penalty_lambda"), 0.0),
    )
    joint_support_evidence_raw = policy_map.get("joint_support_evidence_by_story")
    joint_support_evidence_by_story: Dict[str, float] = {}
    if isinstance(joint_support_evidence_raw, dict):
        for raw_story_id, raw_score in joint_support_evidence_raw.items():
            story_id = str(raw_story_id).strip()
            if not story_id:
                continue
            joint_support_evidence_by_story[story_id] = _clip(_coerce_float(raw_score, 0.0), 0.0, 1.0)

    hunter_judge_split_enabled = bool(policy_map.get("hunter_judge_split_enabled", False))
    hunter_phase_search_loan_credits = max(0, _coerce_int(policy_map.get("hunter_phase_search_loan_credits"), 0))
    hunter_saliency_prepass_raw = policy_map.get("hunter_saliency_prepass_scores")
    hunter_saliency_prepass_scores: Dict[str, float] = {}
    if isinstance(hunter_saliency_prepass_raw, dict):
        for raw_root_id, raw_score in hunter_saliency_prepass_raw.items():
            root_id = str(raw_root_id).strip()
            if not root_id:
                continue
            hunter_saliency_prepass_scores[root_id] = _coerce_float(raw_score, 0.0)
    judge_phase_symmetric_verification_required = bool(
        policy_map.get("judge_phase_symmetric_verification_required", False)
    )
    if judge_phase_symmetric_verification_required:
        decision_contract_enabled = True
        decision_require_counterevidence_probe = True
        decision_min_pairwise_coverage_ratio = max(float(decision_min_pairwise_coverage_ratio), 1.0)

    pair_adjudication_value_prioritization_enabled = bool(
        policy_map.get(
            "pair_adjudication_value_prioritization_enabled",
            policy_map.get("pair_value_prioritization_enabled", False),
        )
    )
    policy_map.setdefault(
        "pair_adjudication_value_prioritization_enabled",
        bool(pair_adjudication_value_prioritization_enabled),
    )
    pair_elimination_value_estimates_raw = policy_map.get("pair_elimination_value_estimates")
    pair_elimination_value_estimates: Dict[str, float] = {}
    if isinstance(pair_elimination_value_estimates_raw, dict):
        for raw_pair_key, raw_value in pair_elimination_value_estimates_raw.items():
            pair_token = str(raw_pair_key).strip().replace("/", "|")
            if "|" not in pair_token:
                continue
            left_raw, right_raw = [part.strip() for part in pair_token.split("|", 1)]
            if not left_raw or not right_raw or left_raw == right_raw:
                continue
            pair_elimination_value_estimates[_pair_key(left_raw, right_raw)] = _coerce_float(raw_value, 0.0)
    quote_fidelity_gate_mode = str(policy_map.get("quote_fidelity_gate_mode", "advisory")).strip().lower()
    if quote_fidelity_gate_mode not in {"strict", "advisory"}:
        quote_fidelity_gate_mode = "advisory"
    evidence_discrimination_tags_required = bool(policy_map.get("evidence_discrimination_tags_required", False))
    evidence_discrimination_tag_mode = str(policy_map.get("evidence_discrimination_tag_mode", "targeted")).strip().lower()
    if evidence_discrimination_tag_mode not in {"targeted", "exhaustive"}:
        evidence_discrimination_tag_mode = "targeted"
    strict_non_discriminative_margin_epsilon = _clip(
        _coerce_float(policy_map.get("strict_non_discriminative_margin_epsilon"), STRICT_NON_DISCRIMINATIVE_EPSILON),
        0.0,
        1.0,
    )
    pair_resolution_engine_raw = policy_map.get("pair_resolution_engine_enabled")
    if pair_resolution_engine_raw is None:
        pair_resolution_engine_enabled = bool(
            strict_contrastive_updates_required and typed_discriminator_evidence_required
        )
    else:
        pair_resolution_engine_enabled = bool(pair_resolution_engine_raw)
    pair_resolution_min_directional_margin = _clip(
        _coerce_float(policy_map.get("pair_resolution_min_directional_margin"), 0.15),
        0.0,
        1.0,
    )
    pair_resolution_min_directional_evidence_count = max(
        1,
        _coerce_int(policy_map.get("pair_resolution_min_directional_evidence_count"), 1),
    )
    pair_resolution_max_contradiction_density = _clip(
        _coerce_float(policy_map.get("pair_resolution_max_contradiction_density"), 0.45),
        0.0,
        1.0,
    )
    pair_resolution_winner_update_gain_default = 0.20 if pair_resolution_engine_enabled else 0.0
    pair_resolution_winner_update_gain = _clip(
        _coerce_float(policy_map.get("pair_resolution_winner_update_gain"), pair_resolution_winner_update_gain_default),
        0.0,
        1.0,
    )
    directional_typed_evidence_linker_enabled = bool(
        policy_map.get("directional_typed_evidence_linker_enabled", False)
    )
    directional_typed_evidence_conflict_policy = str(
        policy_map.get("directional_typed_evidence_conflict_policy", "invalidate")
    ).strip().lower()
    if directional_typed_evidence_conflict_policy not in {"invalidate", "allow"}:
        directional_typed_evidence_conflict_policy = "invalidate"
    contender_retirement_enabled = bool(policy_map.get("contender_retirement_enabled", False))
    contender_retirement_min_decisive_losses = max(
        1,
        _coerce_int(policy_map.get("contender_retirement_min_decisive_losses"), 1),
    )
    contender_retirement_min_resolved_pairs = max(
        1,
        _coerce_int(policy_map.get("contender_retirement_min_resolved_pairs"), 1),
    )
    contender_retirement_min_pair_margin = _clip(
        _coerce_float(policy_map.get("contender_retirement_min_pair_margin"), pair_resolution_min_directional_margin),
        0.0,
        1.0,
    )
    contender_retirement_min_pair_strength = _clip(
        _coerce_float(policy_map.get("contender_retirement_min_pair_strength"), 0.05),
        0.0,
        1.0,
    )
    contender_retirement_require_no_decisive_wins = bool(
        policy_map.get("contender_retirement_require_no_decisive_wins", True)
    )
    contender_retirement_mass_floor = _clip(
        _coerce_float(policy_map.get("contender_retirement_mass_floor"), 0.01),
        0.0,
        1.0,
    )
    contender_retirement_preserve_top_n = max(
        1,
        _coerce_int(policy_map.get("contender_retirement_preserve_top_n"), 1),
    )
    policy_map.setdefault("pair_resolution_engine_enabled", bool(pair_resolution_engine_enabled))
    policy_map.setdefault("pair_resolution_min_directional_margin", float(pair_resolution_min_directional_margin))
    policy_map.setdefault(
        "pair_resolution_min_directional_evidence_count",
        int(pair_resolution_min_directional_evidence_count),
    )
    policy_map.setdefault(
        "pair_resolution_max_contradiction_density",
        float(pair_resolution_max_contradiction_density),
    )
    policy_map.setdefault("pair_resolution_winner_update_gain", float(pair_resolution_winner_update_gain))
    policy_map.setdefault(
        "directional_typed_evidence_linker_enabled",
        bool(directional_typed_evidence_linker_enabled),
    )
    policy_map.setdefault(
        "directional_typed_evidence_conflict_policy",
        str(directional_typed_evidence_conflict_policy),
    )
    policy_map.setdefault("contender_retirement_enabled", bool(contender_retirement_enabled))
    policy_map.setdefault(
        "contender_retirement_min_decisive_losses",
        int(contender_retirement_min_decisive_losses),
    )
    policy_map.setdefault(
        "contender_retirement_min_resolved_pairs",
        int(contender_retirement_min_resolved_pairs),
    )
    policy_map.setdefault(
        "contender_retirement_min_pair_margin",
        float(contender_retirement_min_pair_margin),
    )
    policy_map.setdefault(
        "contender_retirement_min_pair_strength",
        float(contender_retirement_min_pair_strength),
    )
    policy_map.setdefault(
        "contender_retirement_require_no_decisive_wins",
        bool(contender_retirement_require_no_decisive_wins),
    )
    policy_map.setdefault(
        "contender_retirement_mass_floor",
        float(contender_retirement_mass_floor),
    )
    policy_map.setdefault(
        "contender_retirement_preserve_top_n",
        int(contender_retirement_preserve_top_n),
    )
    coverage_confidence_cap_enabled = bool(policy_map.get("coverage_confidence_cap_enabled", False))
    coverage_confidence_cap_base = _clip(
        _coerce_float(policy_map.get("coverage_confidence_cap_base"), 0.40),
        0.0,
        1.0,
    )
    coverage_confidence_cap_gain = _clip(
        _coerce_float(policy_map.get("coverage_confidence_cap_gain"), 0.50),
        0.0,
        1.0,
    )
    contrastive_budget_partition_enabled = bool(policy_map.get("contrastive_budget_partition_enabled", False))
    min_contrastive_discriminator_credits = max(
        0, _coerce_int(policy_map.get("min_contrastive_discriminator_credits"), 0)
    )
    min_counterevidence_credits = max(0, _coerce_int(policy_map.get("min_counterevidence_credits"), 0))
    contrastive_first_required = bool(policy_map.get("contrastive_first_required", False))

    named_root_ids = [rid for rid in hypothesis_set.roots if rid not in {H_NOA_ID, H_UND_ID}]
    hunter_search_loan_remaining = int(hunter_phase_search_loan_credits)
    hunter_target_root_id = ""
    if hunter_judge_split_enabled and hunter_search_loan_remaining > 0 and named_root_ids:
        scored_roots: List[Tuple[float, str]] = []
        for root_id in named_root_ids:
            saliency = float(hunter_saliency_prepass_scores.get(root_id, float(hypothesis_set.ledger.get(root_id, 0.0))))
            scored_roots.append((saliency, root_id))
        scored_roots.sort(key=lambda row: (-row[0], row[1]))
        hunter_target_root_id = str(scored_roots[0][1]) if scored_roots else ""
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
                "policy": dict(policy_map),
                "evidence_items": [_evidence_item_payload(item) for item in evidence_index.values()],
                "evidence_packet_hash": evidence_packet_hash,
            },
        )
    )
    if request.framing:
        deps.audit_sink.append(AuditEvent("FRAMING_RECORDED", {"framing": request.framing}))
    for profile_event in profile_policy_events:
        deps.audit_sink.append(profile_event)
    if compositional_story_space_built:
        deps.audit_sink.append(
            AuditEvent(
                "COMPOSITIONAL_STORY_SPACE_BUILT",
                {
                    "contender_space_mode": contender_space_mode or "singleton_roots",
                    "singleton_stories_explicit_contenders": bool(singleton_stories_explicit_contenders),
                    "roots": list(compositional_story_space_roots),
                    "root_count": len(compositional_story_space_roots),
                },
            )
        )
    if hunter_judge_split_enabled and hunter_target_root_id and hunter_search_loan_remaining > 0:
        deps.audit_sink.append(
            AuditEvent(
                "HUNTER_SEARCH_LOAN_GRANTED",
                {
                    "target_root_id": hunter_target_root_id,
                    "loan_credits": int(hunter_search_loan_remaining),
                    "saliency_scores": {
                        root_id: float(hunter_saliency_prepass_scores.get(root_id, 0.0))
                        for root_id in sorted(hunter_saliency_prepass_scores)
                    },
                },
            )
        )
    if judge_phase_symmetric_verification_required:
        deps.audit_sink.append(
            AuditEvent(
                "JUDGE_VERIFICATION_REQUIRED",
                {
                    "decision_contract_enabled": bool(decision_contract_enabled),
                    "decision_require_counterevidence_probe": bool(decision_require_counterevidence_probe),
                    "decision_min_pairwise_coverage_ratio": float(decision_min_pairwise_coverage_ratio),
                },
            )
        )

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
            AuditEvent(
                "OTHER_ABSORBER_ENFORCED",
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
    strict_delta_bounds: Dict[Tuple[str, str], Dict[str, float]] = {}
    contradiction_floors: Dict[Tuple[str, str], Dict[str, object]] = {}
    strict_signal_counts: Dict[str, int] = {"discriminative": 0, "non_discriminative": 0}
    slot_evaluations_count = 0
    valid_contradictions_count = 0
    root_discriminator_eval_counts: Dict[str, int] = {rid: 0 for rid in named_root_ids}
    root_falsification_counts: Dict[str, int] = {rid: 0 for rid in named_root_ids}
    root_counterevidence_probe_counts: Dict[str, int] = {rid: 0 for rid in named_root_ids}
    observed_discriminator_pairs: set[str] = set()
    pair_target_selection_counts: Dict[str, Dict[str, int]] = {}
    pair_adjudication_active_set_lock_roots: List[str] = []
    pair_catalog: List[str] = []
    pair_catalog_set: set[str] = set()
    pairwise_discriminator_map: Dict[str, str] = {}
    pair_discriminator_ids: Dict[str, str] = {}
    contrastive_discriminator_credits_spent = 0
    counterevidence_probe_credits_spent = 0
    counterevidence_falsification_credits_spent = 0
    counterevidence_probe_plan: Dict[str, object] = {}
    pair_target_context_plan: Dict[str, object] = {}
    pairwise_coverage_for_confidence_cap = float(active_discriminator_coverage_ratio)
    emitted_policy_events: set[Tuple[str, str]] = set()
    pair_resolution_state: Dict[str, Dict[str, object]] = {}
    pair_resolution_cache: Dict[str, Dict[str, object]] = {}
    pair_value_deferred_signatures_emitted: set[str] = set()
    pair_directional_evidence_links: Dict[str, Dict[str, str]] = {}
    retired_root_ids: set[str] = set()
    retired_root_reasons: Dict[str, Dict[str, object]] = {}

    def _ensure_pair_resolution_entry(pair_key: str) -> Dict[str, object]:
        pair = str(pair_key).strip()
        if "|" not in pair:
            pair = str(pair).replace("/", "|")
        if "|" not in pair:
            pair = str(pair)
        canonical = pair if "|" in pair else ""
        if canonical:
            left_raw, right_raw = [part.strip() for part in canonical.split("|", 1)]
            canonical = _pair_key(left_raw, right_raw)
        if not canonical:
            canonical = pair
        if canonical in pair_resolution_state:
            return pair_resolution_state[canonical]
        left, right = canonical.split("|", 1) if "|" in canonical else (canonical, "")
        entry: Dict[str, object] = {
            "pair_key": canonical,
            "left_root_id": left,
            "right_root_id": right,
            "left_score": 0.0,
            "right_score": 0.0,
            "left_records": 0,
            "right_records": 0,
            "directional_records": 0,
            "non_directional_records": 0,
            "invalid_records": 0,
            "total_records": 0,
            "left_evidence_ids": set(),
            "right_evidence_ids": set(),
        }
        pair_resolution_state[canonical] = entry
        return entry

    def _pair_resolution_weight(
        *,
        evidence_quality: str,
        validity: float,
        node_confidence: float,
        evidence_ids: List[str],
        seen_evidence_ids: set[str],
    ) -> float:
        quality_key = str(evidence_quality or "").strip().lower()
        quality_weight = {
            "direct": 1.00,
            "indirect": 0.75,
            "weak": 0.55,
            "none": 0.40,
        }.get(quality_key, 0.70)
        clean_ids = [str(ref).strip() for ref in evidence_ids if str(ref).strip()]
        if clean_ids:
            novel = sum(1 for ref in clean_ids if ref not in seen_evidence_ids)
            novelty_ratio = novel / float(len(clean_ids))
            novelty_weight = 0.50 + 0.50 * novelty_ratio
        else:
            novelty_weight = 0.50
        validity_weight = _clip(float(validity), 0.0, 1.0)
        confidence_weight = 0.50 + 0.50 * _clip(float(node_confidence), 0.0, 1.0)
        return float(quality_weight * novelty_weight * validity_weight * confidence_weight)

    def _record_pair_resolution_observation(
        *,
        pair_key: str,
        direction: str,
        evidence_quality: str,
        validity: float,
        node_confidence: float,
        evidence_ids: List[str],
        invalid: bool,
    ) -> None:
        entry = _ensure_pair_resolution_entry(pair_key)
        entry["total_records"] = int(entry.get("total_records", 0)) + 1
        if invalid:
            entry["invalid_records"] = int(entry.get("invalid_records", 0)) + 1
            pair_resolution_cache.pop(str(entry.get("pair_key", pair_key)), None)
            return
        direction_token = str(direction or "").strip().upper()
        if direction_token not in {"FAVORS_LEFT", "FAVORS_RIGHT"}:
            entry["non_directional_records"] = int(entry.get("non_directional_records", 0)) + 1
            pair_resolution_cache.pop(str(entry.get("pair_key", pair_key)), None)
            return
        side = "left" if direction_token == "FAVORS_LEFT" else "right"
        seen_key = f"{side}_evidence_ids"
        seen_evidence_ids = entry.get(seen_key)
        if not isinstance(seen_evidence_ids, set):
            seen_evidence_ids = set()
            entry[seen_key] = seen_evidence_ids
        weight = _pair_resolution_weight(
            evidence_quality=evidence_quality,
            validity=validity,
            node_confidence=node_confidence,
            evidence_ids=evidence_ids,
            seen_evidence_ids=seen_evidence_ids,
        )
        score_key = f"{side}_score"
        count_key = f"{side}_records"
        entry[score_key] = float(entry.get(score_key, 0.0)) + float(weight)
        entry[count_key] = int(entry.get(count_key, 0)) + 1
        entry["directional_records"] = int(entry.get("directional_records", 0)) + 1
        for ref in evidence_ids:
            token = str(ref).strip()
            if token:
                seen_evidence_ids.add(token)
        pair_resolution_cache.pop(str(entry.get("pair_key", pair_key)), None)

    def _pair_resolution_payload(pair_key: str) -> Dict[str, object]:
        pair = str(pair_key).strip().replace("/", "|")
        if "|" in pair:
            left_raw, right_raw = [part.strip() for part in pair.split("|", 1)]
            pair = _pair_key(left_raw, right_raw)
        cached = pair_resolution_cache.get(pair)
        if isinstance(cached, dict):
            return dict(cached)

        if not pair_resolution_engine_enabled:
            resolved = pair in observed_discriminator_pairs
            verdict = "FAVORS_LEFT" if resolved else "UNRESOLVED"
            left, right = pair.split("|", 1) if "|" in pair else (pair, "")
            payload = {
                "pair_key": pair,
                "left_root_id": left,
                "right_root_id": right,
                "left_score": 1.0 if resolved else 0.0,
                "right_score": 0.0,
                "directional_record_count": 1 if resolved else 0,
                "non_directional_record_count": 0,
                "invalid_record_count": 0,
                "total_record_count": 1 if resolved else 0,
                "margin": 1.0 if resolved else 0.0,
                "strength": 1.0 if resolved else 0.0,
                "contradiction_density": 0.0,
                "verdict": verdict,
                "resolved": bool(resolved),
                "reasons": [] if resolved else ["no_active_discriminator_evidence"],
                "engine_enabled": False,
            }
            pair_resolution_cache[pair] = dict(payload)
            return payload

        entry = _ensure_pair_resolution_entry(pair)
        left_score = float(entry.get("left_score", 0.0))
        right_score = float(entry.get("right_score", 0.0))
        directional_records = int(entry.get("directional_records", 0))
        non_directional_records = int(entry.get("non_directional_records", 0))
        invalid_records = int(entry.get("invalid_records", 0))
        total_records = int(entry.get("total_records", 0))
        directional_total = left_score + right_score
        margin = (
            abs(left_score - right_score) / directional_total
            if directional_total > 1e-12
            else 0.0
        )
        contradiction_density = (
            min(left_score, right_score) / directional_total
            if directional_total > 1e-12
            else 0.0
        )
        reasons: List[str] = []
        if directional_records < int(pair_resolution_min_directional_evidence_count):
            reasons.append("insufficient_directional_evidence")
        if directional_total <= 1e-12:
            reasons.append("zero_directional_weight")
        if margin + 1e-12 < float(pair_resolution_min_directional_margin):
            reasons.append("directional_margin_below_threshold")
        if contradiction_density - 1e-12 > float(pair_resolution_max_contradiction_density):
            reasons.append("contradiction_density_above_ceiling")

        resolved = not reasons
        verdict = "UNRESOLVED"
        if resolved:
            verdict = "FAVORS_LEFT" if left_score >= right_score else "FAVORS_RIGHT"
        strength = 0.0
        if directional_total > 1e-12:
            strength = margin * (1.0 - contradiction_density)
        if not resolved:
            strength = 0.0
        payload = {
            "pair_key": pair,
            "left_root_id": str(entry.get("left_root_id", "")),
            "right_root_id": str(entry.get("right_root_id", "")),
            "left_score": float(left_score),
            "right_score": float(right_score),
            "directional_record_count": int(directional_records),
            "non_directional_record_count": int(non_directional_records),
            "invalid_record_count": int(invalid_records),
            "total_record_count": int(total_records),
            "margin": float(margin),
            "strength": float(strength),
            "contradiction_density": float(contradiction_density),
            "verdict": verdict,
            "resolved": bool(resolved),
            "reasons": list(reasons),
            "engine_enabled": True,
            "min_directional_margin": float(pair_resolution_min_directional_margin),
            "min_directional_evidence_count": int(pair_resolution_min_directional_evidence_count),
            "max_contradiction_density": float(pair_resolution_max_contradiction_density),
        }
        pair_resolution_cache[pair] = dict(payload)
        return payload

    def _resolved_pairs_for_scope(pair_scope_set: set[str]) -> set[str]:
        resolved_pairs: set[str] = set()
        for pair in pair_scope_set:
            payload = _pair_resolution_payload(pair)
            if bool(payload.get("resolved", False)):
                resolved_pairs.add(pair)
        return resolved_pairs

    def _pairwise_resolution_ratio(pair_scope_set: set[str]) -> float:
        if not pair_scope_set:
            return 1.0
        resolved_pairs = _resolved_pairs_for_scope(pair_scope_set)
        return _clip(len(resolved_pairs) / float(len(pair_scope_set)), 0.0, 1.0)

    def _active_named_root_ids() -> List[str]:
        if not contender_retirement_enabled:
            return list(named_root_ids)
        active = [root_id for root_id in named_root_ids if root_id not in retired_root_ids]
        return active if active else list(named_root_ids)

    def _prune_pairs_for_retired_roots(source: str) -> Dict[str, object]:
        nonlocal pair_catalog
        nonlocal pair_catalog_set
        nonlocal pair_catalog_theoretical
        nonlocal pair_catalog_theoretical_set
        nonlocal pairwise_discriminator_map
        nonlocal pair_discriminator_ids
        if not contender_retirement_enabled or not retired_root_ids:
            return {
                "source": source,
                "pruned_pairs": [],
                "pruned_pair_count": 0,
                "active_named_roots": _active_named_root_ids(),
            }

        retired = set(retired_root_ids)

        def _pair_has_retired_root(pair_key: str) -> bool:
            token = str(pair_key or "").strip().replace("/", "|")
            if "|" not in token:
                return False
            left, right = [part.strip() for part in token.split("|", 1)]
            return left in retired or right in retired

        pruned_pairs = [
            pair
            for pair in list(pair_catalog_theoretical)
            if _pair_has_retired_root(pair)
        ]
        if not pruned_pairs:
            return {
                "source": source,
                "pruned_pairs": [],
                "pruned_pair_count": 0,
                "active_named_roots": _active_named_root_ids(),
            }

        pruned_set = set(pruned_pairs)
        pair_catalog_theoretical = [
            pair for pair in list(pair_catalog_theoretical) if pair not in pruned_set
        ]
        pair_catalog = [pair for pair in list(pair_catalog) if pair not in pruned_set]
        pair_catalog_theoretical_set = set(pair_catalog_theoretical)
        pair_catalog_set = set(pair_catalog)
        pairwise_discriminator_map = {
            pair: text
            for pair, text in pairwise_discriminator_map.items()
            if pair not in pruned_set
        }
        pair_discriminator_ids = {
            pair: pair_discriminator_ids.get(pair, _pair_discriminator_id(pair))
            for pair in pair_catalog
        }
        for pair in pruned_pairs:
            pair_target_selection_counts.pop(pair, None)

        return {
            "source": source,
            "pruned_pairs": list(sorted(pruned_set)),
            "pruned_pair_count": int(len(pruned_set)),
            "active_named_roots": _active_named_root_ids(),
        }

    def _retire_contenders_if_decisive(source: str) -> None:
        if not contender_retirement_enabled or not pair_resolution_engine_enabled:
            return
        active_before = [root_id for root_id in _active_named_root_ids() if root_id in hypothesis_set.roots]
        if len(active_before) <= 1:
            return

        ranked_active = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in active_before),
            key=lambda row: (-row[0], row[1]),
        )
        protected_roots = {
            root_id for _, root_id in ranked_active[: max(1, int(contender_retirement_preserve_top_n))]
        }
        retire_rows: List[Tuple[int, float, str, Dict[str, object]]] = []

        active_set = set(active_before)
        for root_id in active_before:
            if root_id in protected_roots:
                continue
            decisive_losses = 0
            decisive_wins = 0
            resolved_pairs = 0
            decisive_losing_pairs: List[str] = []
            for pair_key in list(pair_catalog_theoretical):
                token = str(pair_key).strip()
                if "|" not in token:
                    continue
                left, right = [part.strip() for part in token.split("|", 1)]
                if left not in active_set or right not in active_set:
                    continue
                if root_id not in {left, right}:
                    continue
                payload = _pair_resolution_payload(token)
                if not bool(payload.get("resolved", False)):
                    continue
                verdict = str(payload.get("verdict", "")).strip().upper()
                margin = float(payload.get("margin", 0.0))
                strength = float(payload.get("strength", 0.0))
                if (
                    margin + 1e-12 < float(contender_retirement_min_pair_margin)
                    or strength + 1e-12 < float(contender_retirement_min_pair_strength)
                ):
                    continue
                winner = ""
                if verdict == "FAVORS_LEFT":
                    winner = left
                elif verdict == "FAVORS_RIGHT":
                    winner = right
                if not winner:
                    continue
                resolved_pairs += 1
                if winner == root_id:
                    decisive_wins += 1
                else:
                    decisive_losses += 1
                    decisive_losing_pairs.append(token)

            should_retire = (
                decisive_losses >= int(contender_retirement_min_decisive_losses)
                and resolved_pairs >= int(contender_retirement_min_resolved_pairs)
            )
            if should_retire and contender_retirement_require_no_decisive_wins and decisive_wins > 0:
                should_retire = False
            if not should_retire:
                continue
            retire_rows.append(
                (
                    decisive_losses,
                    float(hypothesis_set.ledger.get(root_id, 0.0)),
                    root_id,
                    {
                        "source": source,
                        "root_id": root_id,
                        "decisive_losses": int(decisive_losses),
                        "decisive_wins": int(decisive_wins),
                        "resolved_pairs": int(resolved_pairs),
                        "decisive_losing_pairs": sorted(set(decisive_losing_pairs)),
                        "min_decisive_losses": int(contender_retirement_min_decisive_losses),
                        "min_resolved_pairs": int(contender_retirement_min_resolved_pairs),
                        "min_pair_margin": float(contender_retirement_min_pair_margin),
                        "min_pair_strength": float(contender_retirement_min_pair_strength),
                        "require_no_decisive_wins": bool(contender_retirement_require_no_decisive_wins),
                    },
                )
            )

        if not retire_rows:
            return

        retire_rows.sort(key=lambda row: (-int(row[0]), -float(row[1]), str(row[2])))
        active_mutable = set(active_before)
        for _, _, root_id, payload in retire_rows:
            if root_id not in active_mutable:
                continue
            if len(active_mutable) <= 1:
                break
            p_before = max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
            p_floor = min(p_before, float(contender_retirement_mass_floor))
            removed_mass = max(0.0, p_before - p_floor)
            survivors = sorted(active_mutable.difference({root_id}))
            survivor_total = sum(max(0.0, float(hypothesis_set.ledger.get(rid, 0.0))) for rid in survivors)
            if removed_mass > 0.0 and survivors:
                if survivor_total <= 1e-12:
                    share = removed_mass / float(len(survivors))
                    for survivor in survivors:
                        hypothesis_set.ledger[survivor] = max(
                            0.0,
                            float(hypothesis_set.ledger.get(survivor, 0.0)) + share,
                        )
                else:
                    for survivor in survivors:
                        prior = max(0.0, float(hypothesis_set.ledger.get(survivor, 0.0)))
                        gain = removed_mass * (prior / survivor_total)
                        hypothesis_set.ledger[survivor] = max(0.0, prior + gain)
            hypothesis_set.ledger[root_id] = p_floor
            retired_root_ids.add(root_id)
            active_mutable.discard(root_id)
            retired_root_reasons[root_id] = dict(payload)
            deps.audit_sink.append(
                AuditEvent(
                    "CONTENDER_RETIRED",
                    {
                        **dict(payload),
                        "p_before": float(p_before),
                        "p_after": float(p_floor),
                        "removed_mass": float(removed_mass),
                        "survivors": list(survivors),
                    },
                )
            )

        named_sum = sum(float(hypothesis_set.ledger.get(root_id, 0.0)) for root_id in named_root_ids)
        if request.config.world_mode != "closed":
            hypothesis_set.ledger[H_NOA_ID] = max(
                0.0,
                1.0 - float(hypothesis_set.ledger.get(H_UND_ID, 0.0)) - float(named_sum),
            )
        for rid in named_root_ids:
            log_ledger[rid] = _safe_log(float(hypothesis_set.ledger.get(rid, 0.0)))

        prune_payload = _prune_pairs_for_retired_roots(source=source)
        if int(prune_payload.get("pruned_pair_count", 0)) > 0:
            deps.audit_sink.append(AuditEvent("CONTENDER_RETIREMENT_PAIR_SCOPE_PRUNED", dict(prune_payload)))

    def _enforce_retired_root_mass_floor(source: str) -> None:
        if not contender_retirement_enabled or not retired_root_ids:
            return
        floor_cap = float(contender_retirement_mass_floor)
        adjusted: Dict[str, Dict[str, float]] = {}
        reclaimed_mass = 0.0
        for root_id in sorted(retired_root_ids):
            before = max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
            after = min(before, floor_cap)
            if before <= after + 1e-12:
                continue
            adjusted[root_id] = {"before": float(before), "after": float(after)}
            reclaimed_mass += float(before - after)
            hypothesis_set.ledger[root_id] = float(after)
        if reclaimed_mass <= 1e-12:
            return

        active_ids = [root_id for root_id in named_root_ids if root_id not in retired_root_ids]
        active_total = sum(max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in active_ids)
        if active_ids:
            if active_total <= 1e-12:
                share = reclaimed_mass / float(len(active_ids))
                for root_id in active_ids:
                    hypothesis_set.ledger[root_id] = max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)) + share)
            else:
                for root_id in active_ids:
                    prior = max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
                    gain = reclaimed_mass * (prior / active_total)
                    hypothesis_set.ledger[root_id] = max(0.0, prior + gain)
        elif request.config.world_mode != "closed":
            hypothesis_set.ledger[H_UND_ID] = _clip(
                float(hypothesis_set.ledger.get(H_UND_ID, 0.0)) + float(reclaimed_mass),
                0.0,
                1.0,
            )

        if request.config.world_mode == "closed":
            total_named = sum(float(hypothesis_set.ledger.get(root_id, 0.0)) for root_id in named_root_ids)
            if total_named > 1e-12:
                scale = 1.0 / total_named
                for root_id in named_root_ids:
                    hypothesis_set.ledger[root_id] = max(
                        0.0,
                        float(hypothesis_set.ledger.get(root_id, 0.0)) * scale,
                    )
        else:
            named_sum = sum(float(hypothesis_set.ledger.get(root_id, 0.0)) for root_id in named_root_ids)
            hypothesis_set.ledger[H_NOA_ID] = max(
                0.0,
                1.0 - float(hypothesis_set.ledger.get(H_UND_ID, 0.0)) - float(named_sum),
            )

        for root_id in named_root_ids:
            log_ledger[root_id] = _safe_log(float(hypothesis_set.ledger.get(root_id, 0.0)))
        deps.audit_sink.append(
            AuditEvent(
                "CONTENDER_RETIREMENT_FLOOR_ENFORCED",
                {
                    "source": source,
                    "floor_cap": float(floor_cap),
                    "reclaimed_mass": float(reclaimed_mass),
                    "adjusted_roots": dict(adjusted),
                    "active_named_roots": list(active_ids),
                },
            )
        )

    def _emit_policy_event_once(event_type: str, key: str, payload: Dict[str, object]) -> None:
        token = (event_type, key)
        if token in emitted_policy_events:
            return
        emitted_policy_events.add(token)
        deps.audit_sink.append(AuditEvent(event_type, payload))

    def _emit_frame_inadequate_anomaly_once() -> None:
        if not frame_inadequate:
            return
        payload = {
            "code": "FRAME_INADEQUATE",
            "frame_adequacy_score": frame_adequacy_score,
            "min_frame_adequacy": min_frame_adequacy,
        }
        _emit_policy_event_once("ANOMALY_FLAGGED", "FRAME_INADEQUATE", payload)

    def _assumption_overlap_score(root_id: str) -> float:
        raw = slot_assumptions_by_root.get(root_id)
        if not isinstance(raw, list):
            return 0.0
        assumptions = [str(item).strip() for item in raw if str(item).strip()]
        if not assumptions:
            return 0.0
        if len(set(assumptions)) == 1:
            return 1.0
        return 1.0 / float(len(set(assumptions)))

    def _dependency_overlap_score(root_id: str, root: RootHypothesis) -> float:
        source = str(root_support_sources.get(root_id, "")).strip()
        if not source:
            return 0.0
        assessed_slots = 0
        for slot_key in required_slot_keys:
            node_key = root.obligations.get(slot_key)
            node = nodes.get(node_key) if node_key else None
            if node and node.assessed:
                assessed_slots += 1
        if assessed_slots >= 2:
            return 1.0
        if assessed_slots == 1:
            return 0.5
        return 0.0

    def _pair_discriminator_id(pair_key: str) -> str:
        return f"disc:{pair_key}"

    def _build_contrastive_context(root_id: str, target_pair_key: Optional[str] = None) -> Dict[str, object]:
        candidates: List[Dict[str, object]] = []
        candidate_ids: List[str] = []
        candidate_pair_keys: set[str] = set()

        def _canonical_pair_key(raw_pair: object) -> str:
            token = str(raw_pair or "").strip().replace("/", "|")
            if "|" not in token:
                return ""
            left_raw, right_raw = [part.strip() for part in token.split("|", 1)]
            if not left_raw or not right_raw or left_raw == right_raw:
                return ""
            return _pair_key(left_raw, right_raw)

        for raw_pair in pair_catalog:
            pair = _canonical_pair_key(raw_pair)
            if not pair or "|" not in pair:
                continue
            left, right = pair.split("|", 1)
            if root_id not in {left, right}:
                continue
            discriminator_id = pair_discriminator_ids.get(pair) or _pair_discriminator_id(pair)
            candidate_ids.append(discriminator_id)
            candidate_pair_keys.add(pair)
            candidate: Dict[str, object] = {
                "pair_key": pair,
                "left_root_id": left,
                "right_root_id": right,
                "discriminator_id": discriminator_id,
            }
            discriminator_text = str(pairwise_discriminator_map.get(pair, "")).strip()
            if discriminator_text:
                candidate["discriminator_text"] = discriminator_text
            candidates.append(candidate)

        primary_pair_key = ""
        default_primary_pair_key = ""
        target_pair = _canonical_pair_key(target_pair_key)
        target_pair_applied = False
        target_pair_injected = False
        target_pair_known = False
        target_pair_involves_root = False
        if target_pair and "|" in target_pair:
            left, right = target_pair.split("|", 1)
            target_pair_involves_root = root_id in {left, right}
            target_pair_known = (
                target_pair in pair_catalog_theoretical_set
                if pair_catalog_theoretical_set
                else bool(target_pair_involves_root)
            )

        if candidates:

            def _other_mass(row: Dict[str, object]) -> float:
                left = str(row.get("left_root_id", "")).strip()
                right = str(row.get("right_root_id", "")).strip()
                other = right if left == root_id else left
                return float(hypothesis_set.ledger.get(other, 0.0))

            candidates = sorted(
                candidates,
                key=lambda row: (-_other_mass(row), str(row.get("pair_key", ""))),
            )
            primary_pair_key = str(candidates[0].get("pair_key", "")).strip()
            default_primary_pair_key = primary_pair_key

        # Queue-selected pair tasks are authoritative for this evaluation.
        # If the selected pair is valid but absent from the globally pruned
        # catalog, inject it so this credit is spent on the intended pair.
        if target_pair and target_pair_known and target_pair_involves_root:
            if target_pair not in candidate_pair_keys:
                left, right = target_pair.split("|", 1)
                discriminator_id = pair_discriminator_ids.get(target_pair) or _pair_discriminator_id(target_pair)
                candidate_ids.append(discriminator_id)
                candidate_pair_keys.add(target_pair)
                injected_candidate: Dict[str, object] = {
                    "pair_key": target_pair,
                    "left_root_id": left,
                    "right_root_id": right,
                    "discriminator_id": discriminator_id,
                }
                discriminator_text = str(pairwise_discriminator_map.get(target_pair, "")).strip()
                if discriminator_text:
                    injected_candidate["discriminator_text"] = discriminator_text
                candidates.append(injected_candidate)
                target_pair_injected = True
            target_rows = [row for row in candidates if str(row.get("pair_key", "")).strip() == target_pair]
            if target_rows:
                primary_pair_key = target_pair
                target_pair_applied = True
                non_target_rows = [row for row in candidates if str(row.get("pair_key", "")).strip() != target_pair]
                candidates = target_rows + non_target_rows

        return {
            "strict_mode": bool(mece_assessment.get("strict")),
            "candidate_pairs": candidates,
            "candidate_discriminator_ids": sorted(set(candidate_ids)),
            "primary_pair_key": primary_pair_key,
            "default_primary_pair_key": default_primary_pair_key,
            "target_pair_key": target_pair,
            "target_pair_applied": bool(target_pair_applied),
            "target_pair_injected": bool(target_pair_injected),
            "target_pair_known": bool(target_pair_known),
            "target_pair_involves_root": bool(target_pair_involves_root),
        }

    def _apply_required_slot_k_cap(root: RootHypothesis, k_cap: float) -> List[str]:
        cap = float(k_cap)
        capped_slots: List[str] = []
        for slot_key in required_slot_keys:
            if required_slot_roles.get(slot_key, "NEC") != "NEC":
                continue
            node_key = root.obligations.get(slot_key)
            node = nodes.get(node_key) if node_key else None
            if not node:
                continue
            if float(node.k) > cap:
                node.k = cap
                capped_slots.append(slot_key)
        if capped_slots:
            _recompute_root_confidence(root, required_slot_keys, required_slot_roles, nodes)
        if float(root.k_root) > cap:
            root.k_root = cap
        return capped_slots

    def _apply_root_confidence_policies(root: RootHypothesis) -> None:
        if root.root_id in {H_NOA_ID, H_UND_ID}:
            return

        if frame_inadequate and not math.isnan(frame_inadequacy_k_cap):
            _emit_frame_inadequate_anomaly_once()
            k_before = float(root.k_root)
            capped_slots = _apply_required_slot_k_cap(root, float(frame_inadequacy_k_cap))
            if k_before > float(frame_inadequacy_k_cap) or capped_slots:
                _emit_policy_event_once(
                    "FRAME_INADEQUACY_CONFIDENCE_CAP_APPLIED",
                    root.root_id,
                    {
                        "root_id": root.root_id,
                        "k_cap": float(frame_inadequacy_k_cap),
                        "k_root_before": k_before,
                        "k_root_after": float(root.k_root),
                        "capped_slots": list(capped_slots),
                        "code": "FRAME_INADEQUATE",
                    },
                )

        if forecasting_cap_active:
            k_before = float(root.k_root)
            capped_slots = _apply_required_slot_k_cap(root, float(forecasting_confidence_cap))
            _emit_policy_event_once(
                "FORECAST_CALIBRATION_CAP_APPLIED",
                root.root_id,
                {
                    "root_id": root.root_id,
                    "confidence_cap": float(forecasting_confidence_cap),
                    "k_root_before": k_before,
                    "k_root_after": float(root.k_root),
                    "capped_slots": list(capped_slots),
                    "reasoning_profile": reasoning_profile,
                    "historical_calibration_status": historical_calibration_status,
                },
            )

        if (
            not math.isnan(evidence_dependency_overlap_threshold)
            and not math.isnan(dependency_penalty_k_cap)
        ):
            overlap = _dependency_overlap_score(root.root_id, root)
            if overlap >= float(evidence_dependency_overlap_threshold):
                k_before = float(root.k_root)
                capped_slots = _apply_required_slot_k_cap(root, float(dependency_penalty_k_cap))
                _emit_policy_event_once(
                    "EVIDENCE_DEPENDENCY_PENALTY_APPLIED",
                    root.root_id,
                    {
                        "root_id": root.root_id,
                        "dependency_overlap": overlap,
                        "threshold": float(evidence_dependency_overlap_threshold),
                        "k_cap": float(dependency_penalty_k_cap),
                        "k_root_before": k_before,
                        "k_root_after": float(root.k_root),
                        "capped_slots": list(capped_slots),
                    },
                )

        if not math.isnan(assumption_overlap_k_cap):
            overlap = _assumption_overlap_score(root.root_id)
            if overlap >= 0.50:
                k_before = float(root.k_root)
                capped_slots = _apply_required_slot_k_cap(root, float(assumption_overlap_k_cap))
                _emit_policy_event_once(
                    "ASSUMPTION_DEPENDENCY_PENALTY_APPLIED",
                    root.root_id,
                    {
                        "root_id": root.root_id,
                        "assumption_overlap": overlap,
                        "k_cap": float(assumption_overlap_k_cap),
                        "k_root_before": k_before,
                        "k_root_after": float(root.k_root),
                        "capped_slots": list(capped_slots),
                    },
                )

        if coverage_confidence_cap_enabled:
            coverage_ratio = _clip(float(pairwise_coverage_for_confidence_cap), 0.0, 1.0)
            k_cap = _clip(
                float(coverage_confidence_cap_base) + float(coverage_confidence_cap_gain) * coverage_ratio,
                0.0,
                1.0,
            )
            if float(root.k_root) > k_cap:
                k_before = float(root.k_root)
                capped_slots = _apply_required_slot_k_cap(root, k_cap)
                _emit_policy_event_once(
                    "COVERAGE_CONFIDENCE_CAP_APPLIED",
                    root.root_id,
                    {
                        "root_id": root.root_id,
                        "coverage_ratio": coverage_ratio,
                        "k_cap": k_cap,
                        "k_root_before": k_before,
                        "k_root_after": float(root.k_root),
                        "capped_slots": list(capped_slots),
                    },
                )

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

    def _pairwise_unresolved_ratio() -> float:
        if pair_adjudication_queue_enabled:
            try:
                snapshot = _current_pair_adjudication_snapshot()
                pair_count = int(snapshot.get("pair_count", 0))
                if pair_count <= 0:
                    return 0.0
                unresolved = int(snapshot.get("unresolved_pairs_count", 0))
                return _clip(unresolved / float(pair_count), 0.0, 1.0)
            except NameError:
                # Snapshot helper is defined later in this scope; fall back to
                # global feasible-pair ratio during initialization.
                pass
        if not pair_catalog_set:
            return 0.0
        resolved_pairs = _resolved_pairs_for_scope(pair_catalog_set)
        unresolved = len(pair_catalog_set.difference(resolved_pairs))
        return _clip(unresolved / float(len(pair_catalog_set)), 0.0, 1.0)

    def _non_discriminative_ratio() -> float:
        non_discriminative = float(strict_signal_counts.get("non_discriminative", 0))
        discriminative = float(strict_signal_counts.get("discriminative", 0))
        total = non_discriminative + discriminative
        if total <= 0.0:
            return 0.0
        return _clip(non_discriminative / total, 0.0, 1.0)

    def _contradiction_density() -> float:
        if slot_evaluations_count <= 0:
            return 0.0
        return _clip(float(valid_contradictions_count) / float(slot_evaluations_count), 0.0, 1.0)

    def _frame_adequacy_gap_ratio() -> float:
        if math.isnan(frame_adequacy_score) or math.isnan(min_frame_adequacy):
            return 0.0
        threshold = float(min_frame_adequacy)
        if threshold <= 0.0:
            return 0.0
        gap = max(0.0, threshold - float(frame_adequacy_score))
        return _clip(gap / threshold, 0.0, 1.0)

    def _dynamic_abstention_floor(
        current_und: float,
        minimum_floor: float = 0.0,
        source: str = "",
    ) -> float:
        und_before = float(current_und)
        if not dynamic_abstention_mass_enabled:
            return max(und_before, float(minimum_floor))
        if len(_active_named_root_ids()) < 2 or not bool(mece_assessment.get("strict")):
            return max(und_before, float(minimum_floor))

        _, base_und = _open_world_gammas(request.config)
        unresolved_pair_ratio = _pairwise_unresolved_ratio()
        contradiction_density = _contradiction_density()
        non_discriminative_ratio = _non_discriminative_ratio()
        frame_adequacy_gap_ratio = _frame_adequacy_gap_ratio()
        if dynamic_abstention_v2_enabled:
            dynamic_raw = (
                float(base_und)
                + float(dynamic_abstention_unresolved_pair_weight) * float(unresolved_pair_ratio)
                + float(dynamic_abstention_contradiction_density_weight) * float(contradiction_density)
                + float(dynamic_abstention_frame_adequacy_weight) * float(frame_adequacy_gap_ratio)
            )
        else:
            dynamic_raw = (
                float(base_und)
                + float(dynamic_abstention_unresolved_pair_weight) * float(unresolved_pair_ratio)
                + float(dynamic_abstention_contradiction_density_weight) * float(contradiction_density)
                + float(dynamic_abstention_non_discriminative_weight) * float(non_discriminative_ratio)
            )

        floor_min = max(float(minimum_floor), float(dynamic_abstention_mass_minimum))
        if fixed_abstention_dominant_floor_enabled:
            floor_min = max(float(floor_min), float(base_und))
        floor_max = max(float(dynamic_abstention_mass_maximum), floor_min)
        dynamic_floor = _clip(dynamic_raw, floor_min, floor_max)
        und_after = max(und_before, dynamic_floor)

        payload = {
            "source": source,
            "applied": bool(und_after > und_before + 1e-12),
            "gamma_und_before": float(und_before),
            "gamma_und_after": float(und_after),
            "base_gamma_und": float(base_und),
            "dynamic_raw": float(dynamic_raw),
            "dynamic_floor": float(dynamic_floor),
            "minimum_floor": float(floor_min),
            "maximum_floor": float(floor_max),
            "unresolved_pair_ratio": float(unresolved_pair_ratio),
            "contradiction_density": float(contradiction_density),
            "non_discriminative_ratio": float(non_discriminative_ratio),
            "frame_adequacy_gap_ratio": float(frame_adequacy_gap_ratio),
            "fixed_dominant_floor_enabled": bool(fixed_abstention_dominant_floor_enabled),
            "weights": {
                "unresolved_pair": float(dynamic_abstention_unresolved_pair_weight),
                "contradiction_density": float(dynamic_abstention_contradiction_density_weight),
                "non_discriminative": float(dynamic_abstention_non_discriminative_weight),
                "frame_adequacy": float(dynamic_abstention_frame_adequacy_weight),
            },
        }
        deps.audit_sink.append(AuditEvent("ABSTENTION_MASS_DYNAMIC_UPDATED", dict(payload)))
        if dynamic_abstention_v2_enabled:
            deps.audit_sink.append(AuditEvent("ABSTENTION_MASS_V2_UPDATED", dict(payload)))
        return float(und_after)

    def _update_open_world_residuals() -> None:
        if request.config.world_mode == "closed":
            return
        active_named_ids = _active_named_root_ids()
        if not active_named_ids:
            return
        # Mismatch: best (minimum) residual over named roots.
        slot_count = max(1, len(required_slot_keys))
        mismatches: List[float] = []
        for root_id in active_named_ids:
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
        for root_id in active_named_ids:
            root = hypothesis_set.roots.get(root_id)
            if not root:
                continue
            for slot_key in required_slot_keys:
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if node and node.assessed:
                    validity_terms.append(1.0 - float(node.validity))
        U = (sum(validity_terms) / len(validity_terms)) if validity_terms else 0.0
        strict_mode = bool(mece_assessment.get("strict"))
        unresolved_ratio = 0.0
        if strict_mode:
            unresolved_ratio = _non_discriminative_ratio()
        if strict_mode and unresolved_ratio > 0.0:
            non_discriminative = float(strict_signal_counts.get("non_discriminative", 0))
            discriminative = float(strict_signal_counts.get("discriminative", 0))
            U = _clip(U + (0.50 * unresolved_ratio), 0.0, 1.0)
            deps.audit_sink.append(
                AuditEvent(
                    "ABSTENTION_PRESSURE_UPDATED",
                    {
                        "non_discriminative_updates": int(non_discriminative),
                        "discriminative_updates": int(discriminative),
                        "unresolved_ratio": unresolved_ratio,
                    },
                )
            )

        eta_M = 0.25
        eta_U = 0.25
        gamma_min = 0.01
        gamma_max = 0.60
        base_noa, base_und = _open_world_gammas(request.config)
        gamma_noa = _clip(base_noa + eta_M * M, gamma_min, gamma_max)
        gamma_und = _clip(base_und + eta_U * U, gamma_min, gamma_max)
        gamma_und_before_dynamic = float(gamma_und)
        gamma_und = _dynamic_abstention_floor(gamma_und, minimum_floor=0.0, source="open_world_gamma")
        strict_floor_applied = bool(gamma_und > gamma_und_before_dynamic + 1e-12)

        uncertainty_tax = 0.0
        if unresolved_contradiction_pressure > 0.0:
            coverage_gap = max(0.0, float(min_discriminator_coverage_ratio) - float(active_discriminator_coverage_ratio))
            uncertainty_tax = max(float(unresolved_contradiction_pressure), coverage_gap)
            if uncertainty_tax > 0.0:
                gamma_und = max(gamma_und, _clip(uncertainty_tax, 0.0, 0.95))
                deps.audit_sink.append(
                    AuditEvent(
                        "UNCERTAINTY_TAX_APPLIED",
                        {
                            "unresolved_contradiction_pressure": float(unresolved_contradiction_pressure),
                            "active_discriminator_coverage_ratio": float(active_discriminator_coverage_ratio),
                            "min_discriminator_coverage_ratio": float(min_discriminator_coverage_ratio),
                            "uncertainty_tax": float(uncertainty_tax),
                            "gamma_und_after_tax": float(gamma_und),
                        },
                    )
                )

        if frame_inadequate and isinstance(frame_inadequacy_reserve, dict):
            reserve_root = str(frame_inadequacy_reserve.get("root_id", "")).strip()
            reserve_mass = _clip(_coerce_float(frame_inadequacy_reserve.get("mass"), 0.0), 0.0, 0.95)
            if reserve_root == H_UND_ID and reserve_mass > 0.0:
                if gamma_und < reserve_mass:
                    gamma_und = reserve_mass
                _emit_frame_inadequate_anomaly_once()
        if gamma_noa + gamma_und >= 0.99:
            scale = 0.99 / max(1e-9, gamma_noa + gamma_und)
            gamma_noa *= scale
            gamma_und *= scale

        retired_named_ids = [root_id for root_id in named_root_ids if root_id not in set(active_named_ids)]
        retired_sum = sum(max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in retired_named_ids)
        total_active = sum(max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in active_named_ids)
        remaining = max(0.0, 1.0 - gamma_noa - gamma_und - retired_sum)
        if active_named_ids:
            if total_active <= 1e-12:
                per_root = remaining / float(len(active_named_ids))
                for root_id in active_named_ids:
                    hypothesis_set.ledger[root_id] = float(per_root)
            else:
                scale = remaining / total_active
                for root_id in active_named_ids:
                    hypothesis_set.ledger[root_id] = max(
                        0.0,
                        float(hypothesis_set.ledger.get(root_id, 0.0)) * scale,
                    )
        hypothesis_set.ledger[H_NOA_ID] = gamma_noa
        hypothesis_set.ledger[H_UND_ID] = gamma_und
        deps.audit_sink.append(
            AuditEvent(
                "OPEN_WORLD_GAMMA_UPDATED",
                {
                    "M": M,
                    "U": U,
                    "unresolved_ratio": unresolved_ratio,
                    "pairwise_unresolved_ratio": float(_pairwise_unresolved_ratio()),
                    "contradiction_density": float(_contradiction_density()),
                    "uncertainty_tax": uncertainty_tax,
                    "strict_abstention_floor_applied": strict_floor_applied,
                    "dynamic_abstention_enabled": bool(dynamic_abstention_mass_enabled),
                    "gamma_noa": gamma_noa,
                    "gamma_und": gamma_und,
                },
            )
        )
        deps.audit_sink.append(
            AuditEvent(
                "OTHER_ABSORBER_ENFORCED",
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
            w_new_raw = _slot_weight(node, weight_cap)
            key = (root.root_id, slot_key)
            w_prev = w_applied.get(key, 0.0)
            raw_delta = float(w_new_raw - w_prev)
            delta = raw_delta

            bound_state = strict_delta_bounds.pop(key, None)
            if bound_state:
                epsilon_nc = float(bound_state.get("epsilon_nc", STRICT_NON_DISCRIMINATIVE_EPSILON))
                bounded = _clip(delta, -epsilon_nc, epsilon_nc)
                if abs(bounded - delta) > 1e-12:
                    deps.audit_sink.append(
                        AuditEvent(
                            "NON_DISCRIMINATIVE_DRIFT_BOUNDED",
                            {
                                "root_id": root.root_id,
                                "slot_key": slot_key,
                                "raw_delta_w": delta,
                                "bounded_delta_w": bounded,
                                "epsilon_nc": epsilon_nc,
                            },
                        )
                    )
                delta = float(bounded)

            contra_state = contradiction_floors.pop(key, None)
            if contra_state:
                floor = -abs(float(contra_state.get("floor", 0.0)))
                if delta > floor:
                    before_penalty = delta
                    delta = floor
                    deps.audit_sink.append(
                        AuditEvent(
                            "CONTRADICTION_PENALTY_APPLIED",
                            {
                                "root_id": root.root_id,
                                "slot_key": slot_key,
                                "delta_w_before": before_penalty,
                                "delta_w_after": delta,
                                "floor": floor,
                                "validity": contra_state.get("validity"),
                                "entailment": contra_state.get("entailment"),
                            },
                        )
                    )

            w_new = w_prev + delta
            total_delta += float(delta)
            w_applied[key] = w_new
            slot_updates.append(
                {
                    "root_id": root.root_id,
                    "slot_key": slot_key,
                    "p_slot": float(node.p),
                    "k_slot": float(node.k),
                    "w_prev": w_prev,
                    "w_raw_new": w_new_raw,
                    "w_new": w_new,
                    "raw_delta_w": raw_delta,
                    "delta_w": delta,
                    "clipped": abs(w_new_raw) >= weight_cap and abs(abs(w_new_raw) - weight_cap) <= 1e-12,
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
        deps.audit_sink.append(
            AuditEvent(
                "MULTIPLIER_COMPUTED",
                {
                    "root_id": root.root_id,
                    "total_delta_w": total_delta,
                    "m": math.exp(total_delta),
                    "beta": beta,
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
        _enforce_retired_root_mass_floor(source="ledger_update")
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

    def evaluate_node(root: RootHypothesis, node_key: str, target_pair_key: Optional[str] = None) -> None:
        nonlocal contrastive_discriminator_credits_spent
        nonlocal counterevidence_falsification_credits_spent
        nonlocal pairwise_coverage_for_confidence_cap
        nonlocal slot_evaluations_count
        nonlocal valid_contradictions_count
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
        contrastive_context = _build_contrastive_context(root_id, target_pair_key=target_pair_key)
        context = {
            "root_id": root_id,
            "root_statement": root.statement,
            "slot_key": slot_key,
            "child_id": child_id,
            "parent_statement": parent_statement,
            "role": node.role,
            "contrastive": contrastive_context,
        }
        deps.audit_sink.append(
            AuditEvent(
                "CONTRASTIVE_CONTEXT_TARGET_BOUND",
                {
                    "root_id": root_id,
                    "slot_key": slot_key,
                    "node_key": node_key,
                    "target_pair_key": str(contrastive_context.get("target_pair_key", "")),
                    "target_pair_applied": bool(contrastive_context.get("target_pair_applied", False)),
                    "target_pair_injected": bool(contrastive_context.get("target_pair_injected", False)),
                    "target_pair_known": bool(contrastive_context.get("target_pair_known", False)),
                    "target_pair_involves_root": bool(contrastive_context.get("target_pair_involves_root", False)),
                    "default_primary_pair_key": str(contrastive_context.get("default_primary_pair_key", "")),
                    "primary_pair_key": str(contrastive_context.get("primary_pair_key", "")),
                    "candidate_pair_count": len(contrastive_context.get("candidate_pairs", [])),
                },
            )
        )
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
        discriminator_ids = outcome.get("discriminator_ids")
        if not isinstance(discriminator_ids, list):
            discriminator_ids = []
        discriminator_ids = [str(item).strip() for item in discriminator_ids if isinstance(item, str) and str(item).strip()]
        discriminator_payloads = outcome.get("discriminator_payloads")
        if not isinstance(discriminator_payloads, list):
            discriminator_payloads = []
        entailment = str(outcome.get("entailment", "UNKNOWN")).strip().upper() or "UNKNOWN"
        non_discriminative = bool(outcome.get("non_discriminative", False))
        evidence_quality = outcome.get("evidence_quality")
        if not isinstance(evidence_quality, str):
            evidence_quality = "none" if not evidence_ids else "indirect"
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
                    if _normalize_quote_text(str(exact_quote)) not in _normalize_quote_text(item.text):
                        quotes_valid = False
                        quote_mismatches.append(str(evidence_id))

        evidence_types_raw = outcome.get("evidence_types")
        evidence_types: List[str] = []
        if isinstance(evidence_types_raw, str):
            evidence_types = [part.strip() for part in evidence_types_raw.split(",") if part.strip()]
        elif isinstance(evidence_types_raw, list):
            evidence_types = [str(item).strip() for item in evidence_types_raw if str(item).strip()]
        primary_evidence_type = evidence_types[0] if evidence_types else "generic_inference"
        inference_weight_multiplier = 1.0
        if inference_weighting_calibration_enabled:
            inference_weight_multiplier = float(
                profile_inference_multipliers.get(
                    primary_evidence_type,
                    profile_inference_multipliers.get("generic_inference", 1.0),
                )
            )
            inference_weight_multiplier = _clip(float(inference_weight_multiplier), 0.0, 1.0)
            proposed_p = 0.5 + (float(proposed_p) - 0.5) * float(inference_weight_multiplier)
            deps.audit_sink.append(
                AuditEvent(
                    "INFERENCE_WEIGHT_PROFILE_APPLIED",
                    {
                        "profile_name": str(reasoning_profile or policy_map.get("profile_name", "generic_causal")),
                        "root_id": root.root_id,
                        "slot_key": slot_key,
                        "source_type": primary_evidence_type,
                        "multiplier": float(inference_weight_multiplier),
                    },
                )
            )

        if not has_refs:
            delta = max(min(proposed_p - previous_p, 0.05), -0.05)
            proposed_p = previous_p + delta
            deps.audit_sink.append(AuditEvent("CONSERVATIVE_DELTA_ENFORCED", {"node_key": node_key, "p_before": previous_p, "p_after": proposed_p}))

        node.p = _clamp_probability(float(proposed_p))
        node.assessed = True
        node.validity = 1.0 if (has_refs and quotes_valid) else 0.0
        if inference_weighting_calibration_enabled:
            node.validity = float(node.validity) * float(inference_weight_multiplier)
        slot_evaluations_count += 1
        strict_mode = bool(mece_assessment.get("strict"))
        slot_state_key = (root.root_id, slot_key)
        typed_discriminator_records: List[Dict[str, object]] = []
        typed_discriminator_invalid_reasons: List[str] = []
        bound_primary_pair_key = str(contrastive_context.get("primary_pair_key", "")).strip()
        bound_target_pair_key = str(contrastive_context.get("target_pair_key", "")).strip()
        bound_target_pair_applied = bool(contrastive_context.get("target_pair_applied", False))
        if typed_discriminator_evidence_required and discriminator_ids and not discriminator_payloads:
            typed_discriminator_invalid_reasons.append("missing_discriminator_payloads")
        if discriminator_payloads:
            for raw_record in discriminator_payloads:
                record_invalid_reasons: List[str] = []
                if not isinstance(raw_record, dict):
                    typed_discriminator_invalid_reasons.append("invalid_discriminator_payload_record")
                    continue
                discriminator_id = str(raw_record.get("id", "")).strip()
                pair = str(raw_record.get("pair", "")).strip().replace("/", "|")
                if "|" in pair:
                    left_raw, right_raw = [part.strip() for part in pair.split("|", 1)]
                    pair = _pair_key(left_raw, right_raw)
                direction = str(raw_record.get("direction", "")).strip().upper()
                typed_evidence_ids = raw_record.get("evidence_ids")
                if not isinstance(typed_evidence_ids, list):
                    typed_evidence_ids = []
                typed_evidence_ids = [
                    str(item).strip()
                    for item in typed_evidence_ids
                    if isinstance(item, str) and str(item).strip()
                ]
                kind = str(raw_record.get("kind", "")).strip().upper()
                claim = str(raw_record.get("claim", "")).strip()
                pair_left = ""
                pair_right = ""
                if "|" in pair:
                    pair_left, pair_right = [part.strip() for part in pair.split("|", 1)]
                supports_direction = ""
                expected_direction = ""
                if pair_left and pair_right and root.root_id in {pair_left, pair_right}:
                    supports_direction = "FAVORS_LEFT" if root.root_id == pair_left else "FAVORS_RIGHT"
                    if entailment == "SUPPORTS":
                        expected_direction = supports_direction
                    elif entailment == "CONTRADICTS":
                        expected_direction = (
                            "FAVORS_RIGHT" if supports_direction == "FAVORS_LEFT" else "FAVORS_LEFT"
                        )
                    if directional_typed_evidence_linker_enabled and direction in {"SUPPORTS", "CONTRADICTS"}:
                        direction = (
                            supports_direction
                            if direction == "SUPPORTS"
                            else ("FAVORS_RIGHT" if supports_direction == "FAVORS_LEFT" else "FAVORS_LEFT")
                        )

                if typed_discriminator_evidence_required:
                    if not discriminator_id:
                        record_invalid_reasons.append("missing_discriminator_id")
                    elif discriminator_id not in discriminator_ids:
                        record_invalid_reasons.append("unknown_discriminator_id")
                    if not pair:
                        record_invalid_reasons.append("missing_pair_key")
                    elif pair_catalog_theoretical_set and pair not in pair_catalog_theoretical_set:
                        record_invalid_reasons.append("unknown_pair_key")
                    if direction and direction not in {"FAVORS_LEFT", "FAVORS_RIGHT", "SUPPORTS", "CONTRADICTS", "NEUTRAL"}:
                        record_invalid_reasons.append("invalid_direction")
                    if not typed_evidence_ids:
                        record_invalid_reasons.append("missing_typed_evidence_ids")
                    elif any(ref not in evidence_index for ref in typed_evidence_ids):
                        record_invalid_reasons.append("typed_evidence_id_not_found")
                    elif has_refs and any(ref not in set(evidence_ids) for ref in typed_evidence_ids):
                        record_invalid_reasons.append("typed_evidence_not_in_outcome_refs")
                    if directional_typed_evidence_linker_enabled:
                        if pair_left and pair_right and root.root_id not in {pair_left, pair_right}:
                            record_invalid_reasons.append("pair_not_linked_to_root_context")
                        if direction not in {"FAVORS_LEFT", "FAVORS_RIGHT"}:
                            record_invalid_reasons.append("direction_not_directional")
                        if (
                            expected_direction
                            and direction in {"FAVORS_LEFT", "FAVORS_RIGHT"}
                            and direction != expected_direction
                        ):
                            record_invalid_reasons.append("direction_entailment_mismatch")
                        if (
                            bound_target_pair_applied
                            and bound_target_pair_key
                            and pair
                            and pair != bound_target_pair_key
                        ):
                            record_invalid_reasons.append("pair_not_bound_to_target_context")
                        elif (
                            not bound_target_pair_applied
                            and bound_primary_pair_key
                            and pair
                            and pair != bound_primary_pair_key
                        ):
                            record_invalid_reasons.append("pair_not_bound_to_primary_context")
                        if pair and direction in {"FAVORS_LEFT", "FAVORS_RIGHT"} and typed_evidence_ids:
                            pair_links = pair_directional_evidence_links.setdefault(pair, {})
                            for evidence_id in typed_evidence_ids:
                                prior_direction = str(pair_links.get(evidence_id, "")).strip().upper()
                                if prior_direction and prior_direction != direction:
                                    record_invalid_reasons.append("typed_evidence_direction_conflict")
                                    deps.audit_sink.append(
                                        AuditEvent(
                                            "TYPED_DIRECTIONAL_EVIDENCE_CONFLICT",
                                            {
                                                "root_id": root.root_id,
                                                "slot_key": slot_key,
                                                "pair_key": pair,
                                                "evidence_id": evidence_id,
                                                "prior_direction": prior_direction,
                                                "new_direction": direction,
                                                "policy": str(directional_typed_evidence_conflict_policy),
                                            },
                                        )
                                    )
                                    if directional_typed_evidence_conflict_policy == "invalidate":
                                        break
                            if not record_invalid_reasons:
                                for evidence_id in typed_evidence_ids:
                                    pair_links[evidence_id] = direction

                if typed_absence_evidence_enabled and claim:
                    if kind == "ABSENCE":
                        deps.audit_sink.append(
                            AuditEvent(
                                "ABSENCE_EVIDENCE_TYPED_ACCEPTED",
                                {
                                    "root_id": root.root_id,
                                    "slot_key": slot_key,
                                    "pair_key": pair,
                                    "claim": claim,
                                    "evidence_ids": list(typed_evidence_ids),
                                },
                            )
                        )
                    else:
                        record_invalid_reasons.append("absence_kind_missing")
                        deps.audit_sink.append(
                            AuditEvent(
                                "ABSENCE_EVIDENCE_UNTYPED_REJECTED",
                                {
                                    "root_id": root.root_id,
                                    "slot_key": slot_key,
                                    "pair_key": pair,
                                    "claim": claim,
                                },
                            )
                        )

                if record_invalid_reasons:
                    typed_discriminator_invalid_reasons.extend(record_invalid_reasons)
                typed_discriminator_records.append(
                    {
                        "id": discriminator_id,
                        "pair": pair,
                        "direction": direction,
                        "evidence_ids": list(typed_evidence_ids),
                        "kind": kind,
                        "claim": claim,
                    }
                )
        if typed_discriminator_evidence_required and discriminator_ids:
            if not has_refs:
                typed_discriminator_invalid_reasons.append("missing_outcome_evidence_refs")
            if entailment not in {"SUPPORTS", "CONTRADICTS"}:
                typed_discriminator_invalid_reasons.append("unsupported_entailment_for_discriminator")

            if typed_discriminator_invalid_reasons:
                deps.audit_sink.append(
                    AuditEvent(
                        "DISCRIMINATOR_EVIDENCE_INVALID",
                        {
                            "root_id": root.root_id,
                            "slot_key": slot_key,
                            "node_key": node_key,
                            "discriminator_ids": list(discriminator_ids),
                            "reasons": sorted(set(typed_discriminator_invalid_reasons)),
                        },
                    )
                )
        quote_fidelity_blocks_discriminator = (
            bool(discriminator_ids)
            and has_refs
            and not quotes_valid
            and quote_fidelity_gate_mode == "strict"
        )
        has_active_discriminator = bool(discriminator_ids) and has_refs and not quote_fidelity_blocks_discriminator
        if typed_discriminator_evidence_required and typed_discriminator_invalid_reasons:
            has_active_discriminator = False

        if bool(discriminator_ids) and has_refs and not quotes_valid:
            deps.audit_sink.append(
                AuditEvent(
                    "QUOTE_FIDELITY_DEGRADED",
                    {
                        "root_id": root.root_id,
                        "slot_key": slot_key,
                        "node_key": node_key,
                        "quote_mismatches": list(quote_mismatches),
                        "quote_fidelity_gate_mode": quote_fidelity_gate_mode,
                        "admission_preserved": bool(has_active_discriminator),
                    },
                )
            )

        tagged_non_discriminative = bool(non_discriminative)
        evidence_discrimination_missing_ids: List[str] = []
        evidence_discrimination_missing_blocks = False
        if (
            strict_mode
            and strict_contrastive_updates_required
            and evidence_discrimination_tags_required
            and has_refs
        ):
            typed_discriminator_evidence_ids: set[str] = set()
            for record in typed_discriminator_records:
                evidence_refs = record.get("evidence_ids")
                if isinstance(evidence_refs, list):
                    typed_discriminator_evidence_ids.update(
                        str(ref).strip()
                        for ref in evidence_refs
                        if isinstance(ref, str) and str(ref).strip()
                    )
            if tagged_non_discriminative:
                typed_discriminator_evidence_ids.update(
                    str(ref).strip()
                    for ref in evidence_ids
                    if isinstance(ref, str) and str(ref).strip()
                )
            evidence_discrimination_missing_ids = sorted(
                {
                    str(ref).strip()
                    for ref in evidence_ids
                    if isinstance(ref, str) and str(ref).strip() and str(ref).strip() not in typed_discriminator_evidence_ids
                }
            )
            if evidence_discrimination_missing_ids:
                candidate_active_discriminator = bool(has_active_discriminator)
                evidence_discrimination_missing_blocks = (
                    evidence_discrimination_tag_mode == "exhaustive"
                    or not candidate_active_discriminator
                )
                deps.audit_sink.append(
                    AuditEvent(
                        "EVIDENCE_DISCRIMINATION_TAGS_MISSING",
                        {
                            "root_id": root.root_id,
                            "slot_key": slot_key,
                            "node_key": node_key,
                            "missing_evidence_ids": list(evidence_discrimination_missing_ids),
                            "tag_mode": evidence_discrimination_tag_mode,
                            "blocking": bool(evidence_discrimination_missing_blocks),
                            "candidate_active_discriminator": bool(candidate_active_discriminator),
                        },
                    )
                )
                if evidence_discrimination_missing_blocks:
                    has_active_discriminator = False

        if strict_mode and not has_active_discriminator and not evidence_discrimination_tags_required:
            tagged_non_discriminative = True
        if strict_mode and strict_contrastive_updates_required and not has_active_discriminator:
            warning_code = "MISSING_ACTIVE_DISCRIMINATOR"
            if evidence_discrimination_missing_ids and evidence_discrimination_missing_blocks:
                warning_code = "MISSING_EVIDENCE_DISCRIMINATION_TAGS"
            deps.audit_sink.append(
                AuditEvent(
                    "POLICY_WARNING",
                    {
                        "warning": warning_code,
                        "policy_warning": warning_code,
                        "root_id": root.root_id,
                        "slot_key": slot_key,
                        "node_key": node_key,
                    },
                )
            )
        if strict_mode:
            if has_active_discriminator:
                strict_signal_counts["discriminative"] = int(strict_signal_counts.get("discriminative", 0)) + 1
                root_discriminator_eval_counts[root.root_id] = int(root_discriminator_eval_counts.get(root.root_id, 0)) + 1
                contrastive_discriminator_credits_spent += 1
                if typed_discriminator_records:
                    for record in typed_discriminator_records:
                        pair = str(record.get("pair", "")).strip().replace("/", "|")
                        if "|" in pair:
                            left_raw, right_raw = [part.strip() for part in pair.split("|", 1)]
                            pair = _pair_key(left_raw, right_raw)
                        if pair and pair in pair_catalog_theoretical_set:
                            observed_discriminator_pairs.add(pair)
                    if pair_catalog_set and not pair_resolution_engine_enabled:
                        pairwise_coverage_for_confidence_cap = len(
                            observed_discriminator_pairs.intersection(pair_catalog_set)
                        ) / float(
                            len(pair_catalog_set)
                        )
                elif pair_catalog_set and len(pair_catalog_set) == 1:
                    observed_discriminator_pairs.update(pair_catalog_set)
                    if not pair_resolution_engine_enabled:
                        pairwise_coverage_for_confidence_cap = 1.0
                deps.audit_sink.append(
                    AuditEvent(
                        "DISCRIMINATOR_EVIDENCE_RECORDED",
                        {
                            "root_id": root.root_id,
                            "slot_key": slot_key,
                            "discriminator_ids": list(discriminator_ids),
                            "typed_records": list(typed_discriminator_records),
                        },
                    )
                )
            elif tagged_non_discriminative:
                strict_signal_counts["non_discriminative"] = int(strict_signal_counts.get("non_discriminative", 0)) + 1
                strict_delta_bounds[slot_state_key] = {
                    "epsilon_nc": float(strict_non_discriminative_margin_epsilon)
                }
                deps.audit_sink.append(
                    AuditEvent(
                        "NON_DISCRIMINATIVE_EVAL_TAGGED",
                        {
                            "root_id": root.root_id,
                            "slot_key": slot_key,
                            "epsilon_nc": float(strict_non_discriminative_margin_epsilon),
                            "discriminator_ids": [],
                        },
                    )
                )
            elif evidence_discrimination_missing_ids:
                strict_signal_counts["non_discriminative"] = int(strict_signal_counts.get("non_discriminative", 0)) + 1
                strict_delta_bounds[slot_state_key] = {"epsilon_nc": 0.0}
                deps.audit_sink.append(
                    AuditEvent(
                        "UNTYPED_EVIDENCE_BLOCKED",
                        {
                            "root_id": root.root_id,
                            "slot_key": slot_key,
                            "node_key": node_key,
                            "missing_evidence_ids": list(evidence_discrimination_missing_ids),
                        },
                    )
                )

        if entailment == "CONTRADICTS" and float(node.validity) >= CONTRADICTION_VALIDITY_MIN:
            valid_contradictions_count += 1
            contradiction_floors[slot_state_key] = {
                "floor": CONTRADICTION_PENALTY_KAPPA * float(node.validity),
                "validity": float(node.validity),
                "entailment": entailment,
            }
            root_falsification_counts[root.root_id] = int(root_falsification_counts.get(root.root_id, 0)) + 1
            counterevidence_falsification_credits_spent += 1
        node_evidence_ids[node_key] = list(evidence_ids)
        node_explanations[node_key] = {
            "evidence_ids": list(evidence_ids),
            "evidence_types": list(evidence_types),
            "discriminator_ids": list(discriminator_ids),
            "discriminator_payloads": list(typed_discriminator_records),
            "non_discriminative": tagged_non_discriminative,
            "entailment": entailment,
            "inference_weight_multiplier": float(inference_weight_multiplier),
            "reasoning_summary": outcome.get("reasoning_summary"),
            "defeaters": outcome.get("defeaters"),
            "uncertainty_source": outcome.get("uncertainty_source"),
            "assumptions": outcome.get("assumptions"),
        }

        rubric = {k: int(outcome[k]) for k in ("A", "B", "C", "D") if k in outcome and str(outcome[k]).isdigit()}
        k_caps: List[Dict[str, object]] = []
        if not has_refs and rubric:
            rubric["A"] = 0
        if rubric:
            node.k, guardrail = _derive_k_from_rubric(rubric)
            node.guardrail_applied = bool(guardrail)
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
        else:
            node.guardrail_applied = False

        pair_resolution_updated_pairs: set[str] = set()
        if strict_mode and pair_resolution_engine_enabled and typed_discriminator_records:
            invalid_pair_observation = bool(typed_discriminator_invalid_reasons) or not bool(has_active_discriminator)
            for record in typed_discriminator_records:
                raw_pair = str(record.get("pair", "")).strip().replace("/", "|")
                if "|" not in raw_pair:
                    continue
                left_raw, right_raw = [part.strip() for part in raw_pair.split("|", 1)]
                pair_key = _pair_key(left_raw, right_raw)
                if pair_catalog_theoretical_set and pair_key not in pair_catalog_theoretical_set:
                    continue
                pair_resolution_updated_pairs.add(pair_key)
                record_evidence_ids = record.get("evidence_ids")
                if not isinstance(record_evidence_ids, list):
                    record_evidence_ids = []
                clean_record_evidence_ids = [
                    str(ref).strip()
                    for ref in record_evidence_ids
                    if isinstance(ref, str) and str(ref).strip()
                ]
                _record_pair_resolution_observation(
                    pair_key=pair_key,
                    direction=str(record.get("direction", "")),
                    evidence_quality=str(evidence_quality),
                    validity=float(node.validity),
                    node_confidence=float(node.k),
                    evidence_ids=clean_record_evidence_ids,
                    invalid=bool(invalid_pair_observation),
                )

        if pair_resolution_engine_enabled and pair_resolution_updated_pairs:
            for pair_key in sorted(pair_resolution_updated_pairs):
                pair_payload = _pair_resolution_payload(pair_key)
                pair_payload["source"] = "node_evaluation"
                deps.audit_sink.append(AuditEvent("PAIR_RESOLUTION_UPDATED", dict(pair_payload)))
            if pair_catalog_set:
                pairwise_coverage_for_confidence_cap = _pairwise_resolution_ratio(pair_catalog_set)

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
                        "evidence_types": list(evidence_types),
                        "discriminator_ids": discriminator_ids,
                        "discriminator_payloads": list(typed_discriminator_records),
                        "non_discriminative": tagged_non_discriminative,
                        "entailment": entailment,
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
                        "inference_weight_multiplier": float(inference_weight_multiplier),
                        "evidence_type": primary_evidence_type,
                        "has_active_discriminator": has_active_discriminator,
                        "tagged_non_discriminative": tagged_non_discriminative,
                        "contrastive_primary_pair_key": str(contrastive_context.get("primary_pair_key", "")),
                        "contrastive_default_primary_pair_key": str(
                            contrastive_context.get("default_primary_pair_key", "")
                        ),
                        "contrastive_target_pair_key": str(contrastive_context.get("target_pair_key", "")),
                        "contrastive_target_pair_applied": bool(
                            contrastive_context.get("target_pair_applied", False)
                        ),
                        "evidence_discrimination_missing_ids": list(evidence_discrimination_missing_ids),
                        "evidence_discrimination_tag_mode": evidence_discrimination_tag_mode,
                        "evidence_discrimination_missing_blocks": bool(evidence_discrimination_missing_blocks),
                        "typed_discriminator_invalid_reasons": sorted(set(typed_discriminator_invalid_reasons)),
                        "quote_fidelity_gate_mode": quote_fidelity_gate_mode,
                        "quote_fidelity_blocks_discriminator": bool(quote_fidelity_blocks_discriminator),
                    },
                    "evidence_packet_hash": evidence_packet_hash,
                    "llm": outcome.get("_provenance"),
                },
            )
        )

        for event in _propagate_parent_updates(node_key, nodes):
            deps.audit_sink.append(event)

        _recompute_root_confidence(root, required_slot_keys, required_slot_roles, nodes)
        _apply_root_confidence_policies(root)

        apply_ledger_update(root)
        _retire_contenders_if_decisive(source="node_evaluation")

    mece_assessment = _assess_mece_certificate(request)
    deps.audit_sink.append(
        AuditEvent(
            "MECE_CERTIFICATE_CHECKED",
            {
                "status": mece_assessment.get("status"),
                "strict": mece_assessment.get("strict"),
                "max_pair_overlap": mece_assessment.get("max_pair_overlap"),
                "pair_count": mece_assessment.get("pair_count"),
                "pairwise_overlap_covered": mece_assessment.get("pairwise_overlap_covered"),
                "pairwise_discriminator_covered": mece_assessment.get("pairwise_discriminator_covered"),
                "issues": list(mece_assessment.get("issues", [])),
            },
        )
    )
    contender_space_assessment = _assess_contender_space(named_root_ids, policy_map)
    deps.audit_sink.append(
        AuditEvent(
            "CONTENDER_SPACE_CHECKED",
            {
                "status": contender_space_assessment.get("status"),
                "mode": contender_space_assessment.get("mode"),
                "explicit_mode": contender_space_assessment.get("explicit_mode"),
                "root_count": contender_space_assessment.get("root_count"),
                "auto_expanded": contender_space_assessment.get("auto_expanded"),
                "max_story_cardinality_limit": contender_space_assessment.get("max_story_cardinality_limit"),
                "max_story_cardinality": contender_space_assessment.get("max_story_cardinality"),
                "multi_factor_story_count": contender_space_assessment.get("multi_factor_story_count"),
                "cardinality_by_root": dict(contender_space_assessment.get("cardinality_by_root", {})),
                "issues": list(contender_space_assessment.get("issues", [])),
            },
        )
    )
    if contender_space_assessment.get("status") == "FAILED":
        deps.audit_sink.append(
            AuditEvent(
                "CONTENDER_SPACE_INVALID",
                {
                    "mode": contender_space_assessment.get("mode"),
                    "issues": list(contender_space_assessment.get("issues", [])),
                },
            )
        )
    pair_catalog_theoretical = _pair_catalog(named_root_ids)
    pair_catalog = list(pair_catalog_theoretical)
    pair_catalog_set = set(pair_catalog)
    pair_catalog_theoretical_set = set(pair_catalog_theoretical)
    raw_pairwise_discriminators = mece_assessment.get("pairwise_discriminators")
    if isinstance(raw_pairwise_discriminators, dict):
        pairwise_discriminator_map = {
            str(pair).strip(): str(text).strip()
            for pair, text in raw_pairwise_discriminators.items()
            if str(pair).strip() in pair_catalog_theoretical_set
        }
    else:
        pairwise_discriminator_map = {}
    def _select_ranked_active_set(
        ranked_named: List[Tuple[float, str]],
        *,
        enabled: bool,
        requested_size: int,
        mass_ratio: float,
        pair_budget: Optional[int] = None,
    ) -> List[str]:
        if contender_retirement_enabled and retired_root_ids:
            ranked_named = [
                (float(probability), str(root_id))
                for probability, root_id in ranked_named
                if str(root_id) not in retired_root_ids
            ]
        if not enabled or len(ranked_named) < 2:
            return []
        winner_prob = float(ranked_named[0][0]) if ranked_named else 0.0
        base_count = max(2, int(requested_size) if int(requested_size) > 0 else 2)
        base_count = min(base_count, len(ranked_named))

        selected: List[str] = []
        for probability, root_id in ranked_named:
            if len(selected) < base_count:
                selected.append(str(root_id))
                continue
            if float(mass_ratio) <= 0.0:
                continue
            threshold = float(winner_prob) * float(mass_ratio)
            if float(probability) + 1e-12 >= threshold:
                selected.append(str(root_id))

        deduped: List[str] = []
        seen: set[str] = set()
        for root_id in selected:
            if root_id in seen:
                continue
            seen.add(root_id)
            deduped.append(root_id)

        if pair_adjudication_budget_feasible_enabled and pair_budget is not None:
            budget_cap = max(0, int(pair_budget))
            max_roots = _max_root_count_for_pair_budget(len(deduped), budget_cap)
            if max_roots < 2:
                return []
            deduped = deduped[:max_roots]
        return deduped

    def _feasible_pair_scope(pair_scope_catalog: List[str]) -> Tuple[List[str], Dict[str, object]]:
        theoretical_pairs = list(pair_scope_catalog)
        theoretical_pair_count = len(theoretical_pairs)
        budget = max(0, int(pair_adjudication_pair_budget))
        if not pair_adjudication_budget_feasible_enabled:
            return theoretical_pairs, {
                "budget_feasible_enabled": False,
                "pair_budget": budget,
                "theoretical_pair_count": theoretical_pair_count,
                "feasible_pair_count": theoretical_pair_count,
            }
        if pair_adjudication_value_prioritization_enabled:
            def _pair_value_row(pair_key: str) -> Tuple[float, float, str]:
                canonical_pair = str(pair_key).strip().replace("/", "|")
                if "|" in canonical_pair:
                    left_raw, right_raw = [part.strip() for part in canonical_pair.split("|", 1)]
                    canonical_pair = _pair_key(left_raw, right_raw)
                left, right = canonical_pair.split("|", 1) if "|" in canonical_pair else (canonical_pair, "")
                pair_mass = max(
                    float(hypothesis_set.ledger.get(left, 0.0)),
                    float(hypothesis_set.ledger.get(right, 0.0)),
                )
                pair_value = float(pair_elimination_value_estimates.get(canonical_pair, pair_mass))
                return (pair_value, pair_mass, canonical_pair)

            ranked_pairs = sorted(
                [str(pair).strip() for pair in theoretical_pairs if str(pair).strip()],
                key=lambda token: (
                    -_pair_value_row(token)[0],
                    -_pair_value_row(token)[1],
                    _pair_value_row(token)[2],
                ),
            )
            if budget <= 0:
                feasible_pairs = []
            else:
                feasible_pairs = ranked_pairs[:budget]
            deferred_pairs = [pair for pair in ranked_pairs if pair not in set(feasible_pairs)]
            if deferred_pairs:
                signature = "|".join(sorted(deferred_pairs))
                if signature not in pair_value_deferred_signatures_emitted:
                    pair_value_deferred_signatures_emitted.add(signature)
                    deps.audit_sink.append(
                        AuditEvent(
                            "PAIR_VALUE_DEFERRED_FOR_BUDGET",
                            {
                                "pair_budget": int(budget),
                                "feasible_pairs": list(feasible_pairs),
                                "deferred_pairs": list(deferred_pairs),
                            },
                        )
                    )
        else:
            feasible_pairs = _limit_pairs_by_budget(
                theoretical_pairs,
                pair_budget=budget,
                ledger=hypothesis_set.ledger,
            )
        return feasible_pairs, {
            "budget_feasible_enabled": True,
            "pair_budget": budget,
            "theoretical_pair_count": theoretical_pair_count,
            "feasible_pair_count": len(feasible_pairs),
        }

    pair_catalog, _ = _feasible_pair_scope(pair_catalog_theoretical)
    pair_catalog_set = set(pair_catalog)
    pair_discriminator_ids = {pair: _pair_discriminator_id(pair) for pair in pair_catalog}
    if pair_resolution_engine_enabled and pair_catalog_set:
        pairwise_coverage_for_confidence_cap = _pairwise_resolution_ratio(pair_catalog_set)

    pairwise_coverage_ratio = _clip(float(active_discriminator_coverage_ratio), 0.0, 1.0)
    pairwise_unresolved_pairs: List[str] = []
    if (
        bool(mece_assessment.get("strict"))
        and strict_contrastive_updates_required
        and pair_catalog
        and pairwise_coverage_ratio + 1e-12 < float(min_discriminator_coverage_ratio)
    ):
        pairwise_unresolved_pairs = list(pair_catalog)
    closure_adjudication_snapshot: Dict[str, object] = {
        "status": "NOT_ENABLED",
        "pairwise_scope": "global",
        "candidate_active_set_roots": [],
        "active_set_roots": [],
        "active_set_pair_count": 0,
        "active_set_theoretical_pair_count": 0,
        "pair_count": int(len(pair_catalog)),
        "theoretical_pair_count": int(len(pair_catalog_theoretical)),
        "pair_budget": int(pair_adjudication_pair_budget),
        "budget_feasible_enabled": bool(pair_adjudication_budget_feasible_enabled),
        "active_set_lock_enabled": bool(pair_adjudication_active_set_lock_enabled),
        "active_set_lock_roots": [],
        "active_set_lock_reused": False,
        "observed_pair_count": 0,
        "resolved_pair_count": 0,
        "resolved_pairs": [],
        "resolved_coverage_ratio": 0.0,
        "coverage_ratio": 0.0,
        "min_pairwise_coverage_ratio": float(closure_min_pairwise_coverage_ratio),
        "unresolved_pairs_count": 0,
        "unresolved_pairs": [],
    }
    pair_adjudication_snapshot: Dict[str, object] = {
        "status": "NOT_ENABLED",
        "scope": pair_adjudication_scope,
        "pairwise_scope": "global",
        "candidate_active_set_roots": [],
        "active_set_roots": [],
        "active_set_pair_count": 0,
        "active_set_theoretical_pair_count": 0,
        "pair_count": int(len(pair_catalog)),
        "theoretical_pair_count": int(len(pair_catalog_theoretical)),
        "pair_budget": int(pair_adjudication_pair_budget),
        "budget_feasible_enabled": bool(pair_adjudication_budget_feasible_enabled),
        "active_set_lock_enabled": bool(pair_adjudication_active_set_lock_enabled),
        "active_set_lock_roots": [],
        "active_set_lock_reused": False,
        "active_set_lock_released": False,
        "balance_targets_enabled": bool(pair_adjudication_balance_targets),
        "min_targets_per_side": int(pair_adjudication_min_targets_per_side),
        "bootstrap_missing_side_enabled": bool(pair_adjudication_bootstrap_missing_side),
        "unresolved_pairs_count": 0,
        "unresolved_pairs": [],
        "observed_pairs": [],
        "resolved_pair_count": 0,
        "resolved_pairs": [],
        "coverage_ratio": 0.0,
    }

    stop_reason: Optional[StopReason] = None
    if mece_assessment.get("status") == "FAILED":
        if run_mode in {"start_only", "until_stops"}:
            stop_reason = StopReason.MECE_CERTIFICATE_FAILED
        else:
            deps.audit_sink.append(
                AuditEvent(
                    "MECE_CERTIFICATE_DEFERRED",
                    {
                        "run_mode": run_mode,
                        "issues": list(mece_assessment.get("issues", [])),
                    },
                )
            )
    if stop_reason is None and contender_space_assessment.get("status") == "FAILED":
        stop_reason = StopReason.POLICY_CONFIG_INCOMPATIBLE

    tau_config = float(request.config.tau)
    tau_effective = float(tau_config)
    static_policy_caps: List[float] = []
    if forecasting_cap_active:
        static_policy_caps.append(_clip(float(forecasting_confidence_cap), 0.0, 1.0))
    if frame_inadequate and not math.isnan(frame_inadequacy_k_cap):
        static_policy_caps.append(_clip(float(frame_inadequacy_k_cap), 0.0, 1.0))
    static_policy_k_cap = min(static_policy_caps) if static_policy_caps else None
    if stop_reason is None and static_policy_k_cap is not None and static_policy_k_cap < tau_config:
        if reasoning_mode == "certify":
            stop_reason = StopReason.POLICY_CONFIG_INCOMPATIBLE
            deps.audit_sink.append(
                AuditEvent(
                    "POLICY_CONFLICT_DETECTED",
                    {
                        "mode": reasoning_mode,
                        "tau_config": float(tau_config),
                        "k_cap": float(static_policy_k_cap),
                    },
                )
            )
        elif reasoning_mode == "explore":
            if allow_policy_tau_relaxation:
                tau_effective = float(static_policy_k_cap)
                deps.audit_sink.append(
                    AuditEvent(
                        "CLOSURE_TARGET_ADJUSTED_FOR_POLICY",
                        {
                            "mode": reasoning_mode,
                            "tau_config": float(tau_config),
                            "tau_effective": float(tau_effective),
                            "k_cap": float(static_policy_k_cap),
                        },
                    )
                )
            else:
                deps.audit_sink.append(
                    AuditEvent(
                        "POLICY_CAP_ACTIVE_WITHOUT_TAU_RELAXATION",
                        {
                            "mode": reasoning_mode,
                            "tau_config": float(tau_config),
                            "k_cap": float(static_policy_k_cap),
                        },
                    )
                )

    if stop_reason is None:
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
        active_named = set(_active_named_root_ids())
        return _compute_frontier(
            [
                root
                for root_id, root in hypothesis_set.roots.items()
                if root_id not in {H_NOA_ID, H_UND_ID} and root_id in active_named
            ],
            hypothesis_set.ledger,
            request.config.epsilon,
            request.config.lambda_voi,
        )

    def _current_pair_adjudication_snapshot() -> Dict[str, object]:
        nonlocal pair_adjudication_active_set_lock_roots
        active_named_ids = _active_named_root_ids()
        ranked_named = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in active_named_ids),
            key=lambda row: (-row[0], row[1]),
        )
        pairwise_scope = "global"
        candidate_active_set_roots: List[str] = []
        active_set_roots: List[str] = []
        pair_scope_catalog_theoretical = list(pair_catalog_theoretical)
        lock_reused = False
        lock_released = False

        if pair_adjudication_scope == "active_set":
            candidate_active_set_roots = _select_ranked_active_set(
                ranked_named,
                enabled=True,
                requested_size=pair_adjudication_active_set_size,
                mass_ratio=pair_adjudication_active_set_mass_ratio,
                pair_budget=pair_adjudication_pair_budget,
            )
            selected_active_set_roots = list(candidate_active_set_roots)
            if pair_adjudication_active_set_lock_enabled:
                locked_roots = list(pair_adjudication_active_set_lock_roots)
                if len(locked_roots) >= 2:
                    locked_roots = [
                        root_id
                        for root_id in locked_roots
                        if root_id in hypothesis_set.roots and root_id in active_named_ids
                    ]
                    lock_pair_scope_theoretical = _pair_catalog(locked_roots) if len(locked_roots) >= 2 else []
                    lock_pair_scope_catalog, _ = _feasible_pair_scope(lock_pair_scope_theoretical)
                    lock_unresolved = set(lock_pair_scope_catalog).difference(observed_discriminator_pairs)
                    if lock_pair_scope_catalog and lock_unresolved:
                        selected_active_set_roots = list(locked_roots)
                        if set(selected_active_set_roots) != set(candidate_active_set_roots):
                            lock_reused = True
                    else:
                        pair_adjudication_active_set_lock_roots = []
                        lock_released = True
                if len(selected_active_set_roots) >= 2:
                    if not pair_adjudication_active_set_lock_roots:
                        pair_adjudication_active_set_lock_roots = list(selected_active_set_roots)
                    else:
                        selected_active_set_roots = list(pair_adjudication_active_set_lock_roots)
                elif len(candidate_active_set_roots) >= 2:
                    selected_active_set_roots = list(candidate_active_set_roots)
                    pair_adjudication_active_set_lock_roots = list(candidate_active_set_roots)
            else:
                pair_adjudication_active_set_lock_roots = []
                selected_active_set_roots = list(candidate_active_set_roots)

            if len(selected_active_set_roots) >= 2:
                active_set_roots = list(selected_active_set_roots)
                pairwise_scope = "active_set"
                pair_scope_catalog_theoretical = _pair_catalog(active_set_roots)

        pair_scope_catalog, pair_scope_meta = _feasible_pair_scope(pair_scope_catalog_theoretical)
        pair_scope_set = set(pair_scope_catalog)

        resolved_pairs = sorted(_resolved_pairs_for_scope(pair_scope_set))
        resolved_pair_set = set(resolved_pairs)
        unresolved_pairs = sorted(pair_scope_set.difference(resolved_pair_set))
        observed_pairs = sorted(observed_discriminator_pairs.intersection(pair_scope_set))
        coverage_ratio = _pairwise_resolution_ratio(pair_scope_set)
        status = "COMPLETE" if not unresolved_pairs else "PENDING"

        return {
            "status": status,
            "scope": pair_adjudication_scope,
            "pairwise_scope": pairwise_scope,
            "candidate_active_set_roots": list(candidate_active_set_roots),
            "active_set_roots": list(active_set_roots),
            "active_set_pair_count": len(pair_scope_catalog) if pairwise_scope == "active_set" else 0,
            "active_set_theoretical_pair_count": (
                len(pair_scope_catalog_theoretical) if pairwise_scope == "active_set" else 0
            ),
            "pair_count": len(pair_scope_catalog),
            "theoretical_pair_count": int(pair_scope_meta.get("theoretical_pair_count", len(pair_scope_catalog))),
            "pair_budget": int(pair_scope_meta.get("pair_budget", pair_adjudication_pair_budget)),
            "budget_feasible_enabled": bool(pair_scope_meta.get("budget_feasible_enabled", False)),
            "active_set_lock_enabled": bool(pair_adjudication_active_set_lock_enabled),
            "active_set_lock_roots": (
                list(pair_adjudication_active_set_lock_roots)
                if pair_adjudication_active_set_lock_enabled
                else []
            ),
            "active_set_lock_reused": bool(lock_reused),
            "active_set_lock_released": bool(lock_released),
            "balance_targets_enabled": bool(pair_adjudication_balance_targets),
            "min_targets_per_side": int(pair_adjudication_min_targets_per_side),
            "bootstrap_missing_side_enabled": bool(pair_adjudication_bootstrap_missing_side),
            "pairs": list(pair_scope_catalog),
            "theoretical_pairs": list(pair_scope_catalog_theoretical),
            "observed_pair_count": len(observed_pairs),
            "observed_pairs": list(observed_pairs),
            "resolved_pair_count": len(resolved_pairs),
            "resolved_pairs": list(resolved_pairs),
            "coverage_ratio": float(coverage_ratio),
            "unresolved_pairs_count": len(unresolved_pairs),
            "unresolved_pairs": list(unresolved_pairs),
        }

    def _current_closure_adjudication_snapshot() -> Dict[str, object]:
        active_named_ids = _active_named_root_ids()
        ranked_named = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in active_named_ids),
            key=lambda row: (-row[0], row[1]),
        )
        pairwise_scope = "global"
        candidate_active_set_roots: List[str] = []
        active_set_roots: List[str] = []
        pair_scope_catalog_theoretical = list(pair_catalog_theoretical)
        lock_reused = False

        candidate_active_set_roots = _select_ranked_active_set(
            ranked_named,
            enabled=closure_active_set_adjudication_required,
            requested_size=closure_active_set_size,
            mass_ratio=closure_active_set_mass_ratio,
            pair_budget=pair_adjudication_pair_budget,
        )
        selected_active_set_roots = list(candidate_active_set_roots)
        if (
            closure_active_set_adjudication_required
            and pair_adjudication_active_set_lock_enabled
            and pair_adjudication_queue_enabled
            and len(pair_adjudication_active_set_lock_roots) >= 2
        ):
            locked_roots = [
                root_id
                for root_id in pair_adjudication_active_set_lock_roots
                if root_id in hypothesis_set.roots and root_id in active_named_ids
            ]
            if len(locked_roots) >= 2:
                selected_active_set_roots = list(locked_roots)
                if set(selected_active_set_roots) != set(candidate_active_set_roots):
                    lock_reused = True
        if closure_active_set_adjudication_required and len(selected_active_set_roots) >= 2:
            active_set_roots = list(selected_active_set_roots)
            pairwise_scope = "active_set"
            pair_scope_catalog_theoretical = _pair_catalog(active_set_roots)

        pair_scope_catalog, pair_scope_meta = _feasible_pair_scope(pair_scope_catalog_theoretical)
        pair_scope_set = set(pair_scope_catalog)

        observed_pair_scope = sorted(observed_discriminator_pairs.intersection(pair_scope_set))
        resolved_pair_scope = sorted(_resolved_pairs_for_scope(pair_scope_set))
        resolved_ratio = (
            len(resolved_pair_scope) / float(len(pair_scope_catalog))
            if pair_scope_catalog
            else 1.0
        )
        observed_ratio = len(observed_pair_scope) / float(len(pair_scope_catalog)) if pair_scope_catalog else 1.0
        effective_ratio = float(resolved_ratio)
        if (
            not pair_resolution_engine_enabled
            and not typed_discriminator_evidence_required
            and strict_contrastive_updates_required
        ):
            effective_ratio = max(float(effective_ratio), float(pairwise_coverage_ratio))
        unresolved_pairs = sorted(pair_scope_set.difference(set(resolved_pair_scope)))

        status = "PASSED"
        if pair_scope_catalog and float(effective_ratio) + 1e-12 < float(closure_min_pairwise_coverage_ratio):
            status = "FAILED"

        return {
            "status": status,
            "pairwise_scope": pairwise_scope,
            "candidate_active_set_roots": list(candidate_active_set_roots),
            "active_set_roots": list(active_set_roots),
            "active_set_pair_count": len(pair_scope_catalog) if pairwise_scope == "active_set" else 0,
            "active_set_theoretical_pair_count": (
                len(pair_scope_catalog_theoretical) if pairwise_scope == "active_set" else 0
            ),
            "pair_count": len(pair_scope_catalog),
            "theoretical_pair_count": int(pair_scope_meta.get("theoretical_pair_count", len(pair_scope_catalog))),
            "pair_budget": int(pair_scope_meta.get("pair_budget", pair_adjudication_pair_budget)),
            "budget_feasible_enabled": bool(pair_scope_meta.get("budget_feasible_enabled", False)),
            "active_set_lock_enabled": bool(pair_adjudication_active_set_lock_enabled),
            "active_set_lock_roots": (
                list(pair_adjudication_active_set_lock_roots)
                if pair_adjudication_active_set_lock_enabled
                else []
            ),
            "active_set_lock_reused": bool(lock_reused),
            "pairs": list(pair_scope_catalog),
            "theoretical_pairs": list(pair_scope_catalog_theoretical),
            "observed_pair_count": len(observed_pair_scope),
            "observed_pairs": list(observed_pair_scope),
            "resolved_pair_count": len(resolved_pair_scope),
            "resolved_pairs": list(resolved_pair_scope),
            "resolved_coverage_ratio": float(resolved_ratio),
            "coverage_ratio": float(effective_ratio),
            "observed_coverage_ratio": float(observed_ratio),
            "min_pairwise_coverage_ratio": float(closure_min_pairwise_coverage_ratio),
            "unresolved_pairs_count": len(unresolved_pairs),
            "unresolved_pairs": list(unresolved_pairs),
        }

    def _closure_gate_issues(frontier: List[RootHypothesis]) -> List[str]:
        nonlocal pairwise_unresolved_pairs
        nonlocal closure_adjudication_snapshot
        issues: List[str] = []
        active_named_ids = _active_named_root_ids()
        if min_winner_margin > 0.0 and active_named_ids:
            ranked = sorted(
                [float(hypothesis_set.ledger.get(rid, 0.0)) for rid in active_named_ids],
                reverse=True,
            )
            margin = ranked[0] - ranked[1] if len(ranked) >= 2 else 1.0
            if margin < float(min_winner_margin):
                issues.append("min_winner_margin")
        if min_decomposition_depth_per_slot > 0:
            check_roots = frontier or [
                root for rid, root in hypothesis_set.roots.items() if rid not in {H_NOA_ID, H_UND_ID}
            ]
            for root in check_roots:
                for slot_key in required_slot_keys:
                    node_key = root.obligations.get(slot_key)
                    if not node_key:
                        issues.append("min_decomposition_depth_per_slot")
                        break
                    if _subtree_depth(node_key, nodes) < int(min_decomposition_depth_per_slot):
                        issues.append("min_decomposition_depth_per_slot")
                        break
                if "min_decomposition_depth_per_slot" in issues:
                    break
        if (
            closure_active_set_adjudication_required
            and bool(mece_assessment.get("strict"))
            and strict_contrastive_updates_required
            and pair_catalog
        ):
            snapshot = _current_closure_adjudication_snapshot()
            closure_adjudication_snapshot = dict(snapshot)
            pairwise_unresolved_pairs = list(snapshot.get("unresolved_pairs", []))
            deps.audit_sink.append(
                AuditEvent(
                    "CLOSURE_ACTIVE_SET_ADJUDICATION_CHECKED",
                    {
                        "status": snapshot.get("status"),
                        "pairwise_scope": snapshot.get("pairwise_scope"),
                        "candidate_active_set_roots": list(snapshot.get("candidate_active_set_roots", [])),
                        "active_set_roots": list(snapshot.get("active_set_roots", [])),
                        "active_set_pair_count": int(snapshot.get("active_set_pair_count", 0)),
                        "active_set_theoretical_pair_count": int(
                            snapshot.get("active_set_theoretical_pair_count", 0)
                        ),
                        "pair_count": int(snapshot.get("pair_count", 0)),
                        "theoretical_pair_count": int(snapshot.get("theoretical_pair_count", 0)),
                        "pair_budget": int(snapshot.get("pair_budget", pair_adjudication_pair_budget)),
                        "budget_feasible_enabled": bool(snapshot.get("budget_feasible_enabled", False)),
                        "active_set_lock_enabled": bool(snapshot.get("active_set_lock_enabled", False)),
                        "active_set_lock_roots": list(snapshot.get("active_set_lock_roots", [])),
                        "active_set_lock_reused": bool(snapshot.get("active_set_lock_reused", False)),
                        "observed_pair_count": int(snapshot.get("observed_pair_count", 0)),
                        "resolved_pair_count": int(snapshot.get("resolved_pair_count", 0)),
                        "resolved_coverage_ratio": float(snapshot.get("resolved_coverage_ratio", 0.0)),
                        "coverage_ratio": float(snapshot.get("coverage_ratio", 0.0)),
                        "min_pairwise_coverage_ratio": float(snapshot.get("min_pairwise_coverage_ratio", 0.0)),
                        "unresolved_pairs_count": int(snapshot.get("unresolved_pairs_count", 0)),
                        "unresolved_pairs": list(snapshot.get("unresolved_pairs", [])),
                    },
                )
            )
            if str(snapshot.get("status", "")).upper() == "FAILED":
                issues.append("active_set_pairwise_coverage")
                deps.audit_sink.append(
                    AuditEvent(
                        "CLOSURE_ACTIVE_SET_ADJUDICATION_INCOMPLETE",
                        {
                            "pairwise_scope": snapshot.get("pairwise_scope"),
                            "candidate_active_set_roots": list(snapshot.get("candidate_active_set_roots", [])),
                            "active_set_roots": list(snapshot.get("active_set_roots", [])),
                            "active_set_lock_reused": bool(snapshot.get("active_set_lock_reused", False)),
                            "unresolved_pairs_count": int(snapshot.get("unresolved_pairs_count", 0)),
                            "unresolved_pairs": list(snapshot.get("unresolved_pairs", [])),
                            "coverage_ratio": float(snapshot.get("coverage_ratio", 0.0)),
                            "min_pairwise_coverage_ratio": float(snapshot.get("min_pairwise_coverage_ratio", 0.0)),
                        },
                    )
                )
        return issues

    def _named_roots_in_order() -> List[RootHypothesis]:
        return [hypothesis_set.roots[rid] for rid in _active_named_root_ids() if rid in hypothesis_set.roots]

    def _required_slots_assessed(root: RootHypothesis) -> bool:
        for slot_key in required_slot_keys:
            if required_slot_roles.get(slot_key, "NEC") != "NEC":
                continue
            node_key = root.obligations.get(slot_key)
            if not node_key:
                return False
            node = nodes.get(node_key)
            if node is None or not node.assessed:
                return False
        return True

    def _root_has_confidence_gap(root: RootHypothesis, tau_target: float) -> bool:
        for slot_key in required_slot_keys:
            if required_slot_roles.get(slot_key, "NEC") != "NEC":
                continue
            node_key = root.obligations.get(slot_key)
            if not node_key:
                return True
            node = nodes.get(node_key)
            if node is None:
                return True
            if float(node.k) < float(tau_target):
                return True
        return False

    def _is_epistemic_limit(tau_target: float) -> bool:
        if reasoning_mode not in {"certify", "explore"}:
            return False
        if run_mode not in {"until_stops", "operations", "until_credits_exhausted"}:
            return False
        roots = _named_roots_in_order()
        if not roots:
            return False
        if any(root.status != "SCOPED" for root in roots):
            return False
        _, frontier = _compute_frontier(
            roots,
            hypothesis_set.ledger,
            request.config.epsilon,
            request.config.lambda_voi,
        )
        focus_roots = frontier or roots
        if not any(_root_has_confidence_gap(root, tau_target) for root in focus_roots):
            return False
        if any(not _required_slots_assessed(root) for root in focus_roots):
            return False
        if _frontier_confident(
            focus_roots,
            required_slot_keys,
            nodes,
            tau_target,
            min_decomposition_depth_per_slot,
        ):
            return False
        for root in focus_roots:
            nxt = _legal_next_for_root(
                root,
                required_slot_keys,
                tau_target,
                nodes,
                credits_remaining,
                deps.decomposer,
                min_decomposition_depth_per_slot,
            )
            if nxt is not None:
                return False
        return True

    def _generate_next_steps(tau_target: float) -> List[Dict[str, object]]:
        recommendations: List[Dict[str, object]] = []
        for root in _named_roots_in_order():
            raw_assumptions = slot_assumptions_by_root.get(root.root_id)
            assumptions: List[str] = []
            if isinstance(raw_assumptions, list):
                assumptions = [str(item).strip() for item in raw_assumptions if str(item).strip()]
            for slot_key in required_slot_keys:
                if required_slot_roles.get(slot_key, "NEC") != "NEC":
                    continue
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if node is None:
                    continue
                k_current = float(node.k)
                if bool(node.assessed) and k_current >= float(tau_target):
                    continue
                recommendations.append(
                    {
                        "root_id": root.root_id,
                        "slot_key": slot_key,
                        "node_key": node.node_key,
                        "k_current": k_current,
                        "p_current": float(node.p),
                        "assessed": bool(node.assessed),
                        "tau_target": float(tau_target),
                        "gap_to_target": max(0.0, float(tau_target) - k_current),
                        "assumptions": list(assumptions),
                        "reason": "confidence_gap" if node.assessed else "unassessed_required_slot",
                    }
                )
        recommendations.sort(
            key=lambda row: (
                -float(row.get("gap_to_target", 0.0)),
                str(row.get("root_id", "")),
                str(row.get("slot_key", "")),
            )
        )
        return recommendations

    def _counterevidence_probe_credits_needed() -> int:
        if not contrastive_budget_partition_enabled:
            return 0
        return max(0, int(min_counterevidence_credits) - int(counterevidence_probe_credits_spent))

    def _current_leader_root_id() -> str:
        active_named_ids = _active_named_root_ids()
        if not active_named_ids:
            return ""
        ranked = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in active_named_ids),
            key=lambda item: (-item[0], item[1]),
        )
        return str(ranked[0][1]) if ranked else ""

    def _select_partition_candidate(
        candidates: List[Tuple[float, str, str, str, RootHypothesis]],
    ) -> Optional[Tuple[float, str, str, str, RootHypothesis]]:
        nonlocal pair_adjudication_snapshot
        nonlocal counterevidence_probe_plan
        nonlocal pair_target_context_plan
        counterevidence_probe_plan = {}
        pair_target_context_plan = {}
        if (
            not contrastive_budget_partition_enabled
            and not contrastive_first_required
            and not pair_adjudication_queue_enabled
        ):
            return None
        eval_rows = [row for row in candidates if row[2] == "EVALUATE"]
        counterevidence_credits_needed = _counterevidence_probe_credits_needed()
        needs_counterevidence_budget = counterevidence_credits_needed > 0
        reservation_tight = needs_counterevidence_budget and int(credits_remaining) <= int(counterevidence_credits_needed)
        if pair_adjudication_queue_enabled:
            if bool(mece_assessment.get("strict")) and pair_catalog:
                snapshot = _current_pair_adjudication_snapshot()
                pair_adjudication_snapshot = dict(snapshot)
                deps.audit_sink.append(
                    AuditEvent(
                        "PAIR_ADJUDICATION_QUEUE_UPDATED",
                        {
                            "status": snapshot.get("status"),
                            "scope": snapshot.get("scope"),
                            "pairwise_scope": snapshot.get("pairwise_scope"),
                            "candidate_active_set_roots": list(snapshot.get("candidate_active_set_roots", [])),
                            "active_set_roots": list(snapshot.get("active_set_roots", [])),
                            "active_set_pair_count": int(snapshot.get("active_set_pair_count", 0)),
                            "active_set_theoretical_pair_count": int(
                                snapshot.get("active_set_theoretical_pair_count", 0)
                            ),
                            "pair_count": int(snapshot.get("pair_count", 0)),
                            "theoretical_pair_count": int(snapshot.get("theoretical_pair_count", 0)),
                            "pair_budget": int(snapshot.get("pair_budget", pair_adjudication_pair_budget)),
                            "budget_feasible_enabled": bool(snapshot.get("budget_feasible_enabled", False)),
                            "active_set_lock_enabled": bool(snapshot.get("active_set_lock_enabled", False)),
                            "active_set_lock_roots": list(snapshot.get("active_set_lock_roots", [])),
                            "active_set_lock_reused": bool(snapshot.get("active_set_lock_reused", False)),
                            "active_set_lock_released": bool(snapshot.get("active_set_lock_released", False)),
                            "balance_targets_enabled": bool(snapshot.get("balance_targets_enabled", False)),
                            "min_targets_per_side": int(snapshot.get("min_targets_per_side", 1)),
                            "bootstrap_missing_side_enabled": bool(
                                snapshot.get("bootstrap_missing_side_enabled", False)
                            ),
                            "observed_pair_count": int(snapshot.get("observed_pair_count", 0)),
                            "resolved_pair_count": int(snapshot.get("resolved_pair_count", 0)),
                            "coverage_ratio": float(snapshot.get("coverage_ratio", 0.0)),
                            "unresolved_pairs_count": int(snapshot.get("unresolved_pairs_count", 0)),
                            "unresolved_pairs": list(snapshot.get("unresolved_pairs", [])),
                        },
                    )
                )
                if bool(snapshot.get("active_set_lock_reused", False)):
                    deps.audit_sink.append(
                        AuditEvent(
                            "PAIR_ADJUDICATION_ACTIVE_SET_REUSED",
                            {
                                "candidate_active_set_roots": list(snapshot.get("candidate_active_set_roots", [])),
                                "locked_active_set_roots": list(snapshot.get("active_set_lock_roots", [])),
                                "unresolved_pairs_count": int(snapshot.get("unresolved_pairs_count", 0)),
                            },
                        )
                    )

                unresolved_pairs = list(snapshot.get("unresolved_pairs", []))
                if unresolved_pairs:
                    def _pair_rank(pair_key: str) -> Tuple[float, float, str]:
                        left, right = pair_key.split("|", 1) if "|" in pair_key else (pair_key, "")
                        pair_mass = max(
                            float(hypothesis_set.ledger.get(left, 0.0)),
                            float(hypothesis_set.ledger.get(right, 0.0)),
                        )
                        pair_value = (
                            float(pair_elimination_value_estimates.get(pair_key, pair_mass))
                            if pair_adjudication_value_prioritization_enabled
                            else pair_mass
                        )
                        return (-pair_value, -pair_mass, pair_key)

                    if pair_adjudication_value_prioritization_enabled:
                        ranking_rows = []
                        for pair_key in unresolved_pairs:
                            left, right = pair_key.split("|", 1) if "|" in pair_key else (pair_key, "")
                            pair_mass = max(
                                float(hypothesis_set.ledger.get(left, 0.0)),
                                float(hypothesis_set.ledger.get(right, 0.0)),
                            )
                            pair_value = float(pair_elimination_value_estimates.get(pair_key, pair_mass))
                            ranking_rows.append(
                                {
                                    "pair_key": pair_key,
                                    "elimination_value": float(pair_value),
                                    "pair_mass": float(pair_mass),
                                }
                            )
                        ranking_rows.sort(
                            key=lambda row: (
                                -float(row.get("elimination_value", 0.0)),
                                -float(row.get("pair_mass", 0.0)),
                                str(row.get("pair_key", "")),
                            )
                        )
                        deps.audit_sink.append(
                            AuditEvent(
                                "PAIR_VALUE_PRIORITY_COMPUTED",
                                {
                                    "ranked_pairs": list(ranking_rows),
                                    "pair_budget": int(pair_adjudication_pair_budget),
                                },
                            )
                        )

                    unresolved_pairs.sort(key=_pair_rank)
                    selected_pair = str(unresolved_pairs[0]).strip()
                    selected_roots = [rid for rid in selected_pair.split("|") if rid]
                    selected_root_set = set(selected_roots)
                    pair_target_counts = pair_target_selection_counts.setdefault(
                        selected_pair,
                        {root_id: 0 for root_id in selected_roots},
                    )
                    for root_id in selected_roots:
                        pair_target_counts.setdefault(root_id, 0)

                    deficit_roots: List[str] = []
                    if pair_adjudication_balance_targets:
                        deficit_roots = [
                            root_id
                            for root_id in selected_roots
                            if int(pair_target_counts.get(root_id, 0)) < int(pair_adjudication_min_targets_per_side)
                        ]
                    pair_eval_rows = [
                        row for row in eval_rows if str(row[4].root_id).strip() in selected_root_set
                    ]
                    pair_rows = pair_eval_rows or [
                        row for row in candidates if str(row[4].root_id).strip() in selected_root_set
                    ]
                    if pair_rows:
                        deficit_set = set(deficit_roots)
                        if deficit_roots:
                            present_roots = {str(row[4].root_id).strip() for row in pair_rows}
                            missing_deficit_roots = [
                                root_id for root_id in deficit_roots if root_id not in present_roots
                            ]
                            if missing_deficit_roots and pair_adjudication_bootstrap_missing_side:
                                lambda_voi = float(request.config.lambda_voi)
                                for root_id in missing_deficit_roots:
                                    root_obj = hypothesis_set.roots.get(root_id)
                                    if root_obj is None:
                                        continue
                                    nxt = _legal_next_for_root(
                                        root_obj,
                                        required_slot_keys,
                                        tau_effective,
                                        nodes,
                                        credits_remaining,
                                        deps.decomposer,
                                        min_decomposition_depth_per_slot,
                                    )
                                    if nxt is None:
                                        continue
                                    op_type, target_id = nxt
                                    node = nodes.get(target_id)
                                    p_val = float(node.p) if node else 0.5
                                    k_val = float(node.k) if node else float(root_obj.k_root)
                                    if p_val <= 0.0 or p_val >= 1.0:
                                        entropy = 0.0
                                    else:
                                        entropy = -(p_val * math.log(p_val) + (1.0 - p_val) * math.log(1.0 - p_val))
                                    voi = float(hypothesis_set.ledger.get(root_obj.root_id, 0.0)) * (
                                        1.0 - k_val
                                    ) + lambda_voi * entropy
                                    pair_rows.append((voi, root_obj.canonical_id, op_type, target_id, root_obj))
                                    deps.audit_sink.append(
                                        AuditEvent(
                                            "PAIR_ADJUDICATION_MISSING_SIDE_BOOTSTRAPPED",
                                            {
                                                "pair_key": selected_pair,
                                                "target_root_id": root_obj.root_id,
                                                "target_id": target_id,
                                                "op_type": op_type,
                                                "reason": "missing_deficit_root_candidate",
                                            },
                                        )
                                    )

                        if deficit_set:
                            deficit_rows = [
                                row for row in pair_rows if str(row[4].root_id).strip() in deficit_set
                            ]
                            if deficit_rows:
                                pair_rows = deficit_rows

                        if needs_counterevidence_budget:
                            leader_root_id = _current_leader_root_id()
                            eval_pair_rows = [row for row in pair_rows if row[2] == "EVALUATE"]
                            non_leader_eval_rows = [
                                row
                                for row in eval_pair_rows
                                if str(row[4].root_id).strip() != str(leader_root_id).strip()
                            ]
                            prioritized_probe_rows = non_leader_eval_rows or eval_pair_rows
                            if prioritized_probe_rows:
                                pair_rows = prioritized_probe_rows
                            elif reservation_tight:
                                return None

                        pair_rows.sort(
                            key=lambda row: (
                                0 if row[2] == "EVALUATE" else 1,
                                (
                                    int(root_counterevidence_probe_counts.get(row[4].root_id, 0))
                                    if needs_counterevidence_budget
                                    else 0
                                ),
                                int(pair_target_counts.get(str(row[4].root_id).strip(), 0)),
                                int(root_discriminator_eval_counts.get(row[4].root_id, 0)),
                                row[1],
                                row[3],
                            )
                        )
                        selected_row = pair_rows[0]
                        selected_root_id = str(selected_row[4].root_id).strip()
                        selected_target_id = str(selected_row[3]).strip()
                        selected_op_type = str(selected_row[2]).strip().upper()
                        pair_target_counts[selected_root_id] = int(pair_target_counts.get(selected_root_id, 0)) + 1
                        if selected_op_type == "EVALUATE":
                            pair_target_context_plan = {
                                "root_id": selected_root_id,
                                "target_id": selected_target_id,
                                "pair_key": selected_pair,
                                "reason": "pair_adjudication_queue",
                            }
                        if needs_counterevidence_budget and selected_op_type == "EVALUATE":
                            counterevidence_probe_plan = {
                                "root_id": selected_root_id,
                                "target_id": selected_target_id,
                                "reason": "pair_adjudication_counterevidence_preemption",
                                "pair_key": selected_pair,
                                "credits_needed_before": int(counterevidence_credits_needed),
                            }
                            deps.audit_sink.append(
                                AuditEvent(
                                    "COUNTEREVIDENCE_PREEMPTION_APPLIED",
                                    {
                                        "reason": "pair_adjudication_counterevidence_preemption",
                                        "pair_key": selected_pair,
                                        "target_root_id": selected_root_id,
                                        "target_id": selected_target_id,
                                        "credits_needed_before": int(counterevidence_credits_needed),
                                        "credits_remaining_before": int(credits_remaining),
                                    },
                                )
                            )
                        deps.audit_sink.append(
                            AuditEvent(
                                "PAIR_ADJUDICATION_TARGET_SELECTED",
                                {
                                    "pair_key": selected_pair,
                                    "candidate_roots": sorted(selected_roots),
                                    "target_root_id": selected_root_id,
                                    "target_id": selected_target_id,
                                    "op_type": selected_op_type,
                                    "unresolved_pairs_count": len(unresolved_pairs),
                                    "deficit_roots": list(deficit_roots),
                                    "pair_target_counts": dict(pair_target_counts),
                                },
                            )
                        )
                        return selected_row
            else:
                pair_adjudication_snapshot = {
                    "status": "SKIPPED",
                    "scope": pair_adjudication_scope,
                    "pairwise_scope": "global",
                    "candidate_active_set_roots": [],
                    "active_set_roots": [],
                    "active_set_pair_count": 0,
                    "active_set_theoretical_pair_count": 0,
                    "pair_count": int(len(pair_catalog)),
                    "theoretical_pair_count": int(len(pair_catalog_theoretical)),
                    "pair_budget": int(pair_adjudication_pair_budget),
                    "budget_feasible_enabled": bool(pair_adjudication_budget_feasible_enabled),
                    "active_set_lock_enabled": bool(pair_adjudication_active_set_lock_enabled),
                    "active_set_lock_roots": list(pair_adjudication_active_set_lock_roots),
                    "active_set_lock_reused": False,
                    "active_set_lock_released": False,
                    "balance_targets_enabled": bool(pair_adjudication_balance_targets),
                    "min_targets_per_side": int(pair_adjudication_min_targets_per_side),
                    "bootstrap_missing_side_enabled": bool(pair_adjudication_bootstrap_missing_side),
                    "unresolved_pairs_count": 0,
                    "unresolved_pairs": [],
                    "observed_pairs": [],
                    "resolved_pair_count": 0,
                    "resolved_pairs": [],
                    "coverage_ratio": 0.0,
                    "reason": "pair_adjudication_requires_strict_contrastive_mece",
                }

        if not eval_rows:
            return None
        if contrastive_first_required and pair_catalog:
            eval_rows = [
                row for row in eval_rows if str(row[4].root_id).strip() in {rid for pair in pair_catalog for rid in pair.split("|")}
            ] or eval_rows
        needs_discriminator_budget = (
            contrastive_budget_partition_enabled
            and int(min_contrastive_discriminator_credits) > int(contrastive_discriminator_credits_spent)
        )
        if needs_discriminator_budget:
            eval_rows.sort(
                key=lambda row: (
                    int(root_discriminator_eval_counts.get(row[4].root_id, 0)),
                    row[1],
                    row[3],
                )
            )
            return eval_rows[0]

        if needs_counterevidence_budget:
            leader_root_id = _current_leader_root_id()
            non_leader = [row for row in eval_rows if str(row[4].root_id).strip() != str(leader_root_id).strip()]
            if non_leader:
                non_leader.sort(
                    key=lambda row: (
                        int(root_counterevidence_probe_counts.get(row[4].root_id, 0)),
                        int(root_falsification_counts.get(row[4].root_id, 0)),
                        row[1],
                        row[3],
                    )
                )
                selected_row = non_leader[0]
            else:
                eval_rows.sort(
                    key=lambda row: (
                        int(root_counterevidence_probe_counts.get(row[4].root_id, 0)),
                        int(root_falsification_counts.get(row[4].root_id, 0)),
                        row[1],
                        row[3],
                    )
                )
                selected_row = eval_rows[0]
            selected_root_id = str(selected_row[4].root_id).strip()
            selected_target_id = str(selected_row[3]).strip()
            counterevidence_probe_plan = {
                "root_id": selected_root_id,
                "target_id": selected_target_id,
                "reason": "counterevidence_budget_partition",
                "credits_needed_before": int(counterevidence_credits_needed),
            }
            deps.audit_sink.append(
                AuditEvent(
                    "COUNTEREVIDENCE_PREEMPTION_APPLIED",
                    {
                        "reason": "counterevidence_budget_partition",
                        "target_root_id": selected_root_id,
                        "target_id": selected_target_id,
                        "credits_needed_before": int(counterevidence_credits_needed),
                        "credits_remaining_before": int(credits_remaining),
                    },
                )
            )
            return selected_row
        return None

    next_steps: List[Dict[str, object]] = []
    next_steps_event_emitted = False

    rr_index = 0
    last_frontier_signature: Optional[Tuple[str, ...]] = None

    if stop_reason is None and run_mode == "start_only":
        if credits_remaining <= 0:
            stop_reason = StopReason.CREDITS_EXHAUSTED
    elif stop_reason is None:
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
                and _frontier_confident(
                    frontier,
                    required_slot_keys,
                    nodes,
                    tau_effective,
                    min_decomposition_depth_per_slot,
                )
            ):
                closure_issues = _closure_gate_issues(frontier)
                if closure_issues:
                    deps.audit_sink.append(
                        AuditEvent(
                            "FRONTIER_CONFIDENCE_DEFERRED",
                            {
                                "leader_id": leader_id,
                                "frontier": [r.root_id for r in frontier],
                                "issues": list(closure_issues),
                                "min_winner_margin": float(min_winner_margin),
                                "min_decomposition_depth_per_slot": int(min_decomposition_depth_per_slot),
                            },
                        )
                    )
                    stop_reason = StopReason.CLOSURE_GATES_UNMET
                else:
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
                            nxt = _legal_next_for_root(
                                root,
                                required_slot_keys,
                                tau_effective,
                                nodes,
                                credits_remaining,
                                deps.decomposer,
                                min_decomposition_depth_per_slot,
                            )
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
                if node_key:
                    explicit_root_id = str(node_key).split(":", 1)[0]
                    explicit_root = hypothesis_set.roots.get(explicit_root_id)
                    if explicit_root is not None:
                        target_root = explicit_root
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
                    selected_slot = _select_slot_lowest_k(target_root, required_slot_keys, nodes, tau_effective)
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
                nxt = _legal_next_for_root(
                    root,
                    required_slot_keys,
                    tau_effective,
                    nodes,
                    credits_remaining,
                    deps.decomposer,
                    min_decomposition_depth_per_slot,
                )
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
                if (
                    hunter_judge_split_enabled
                    and hunter_search_loan_remaining > 0
                    and hunter_target_root_id
                    and str(root.root_id).strip() == str(hunter_target_root_id).strip()
                ):
                    # Favor hunter-selected lead while loan credits remain.
                    voi += 1.0
                deps.audit_sink.append(
                    AuditEvent(
                        "VOI_SCORED",
                        {
                            "root_id": root.root_id,
                            "target_id": target_id,
                            "voi": voi,
                            "hunter_bonus_applied": bool(
                                hunter_judge_split_enabled
                                and hunter_search_loan_remaining > 0
                                and str(root.root_id).strip() == str(hunter_target_root_id).strip()
                            ),
                            "p_node": p_val,
                            "k_node": k_val,
                            "lambda_voi": lambda_voi,
                        },
                    )
                )
                candidates.append((voi, root.canonical_id, op_type, target_id, root))

            if eval_share < rho and all(root.status == "SCOPED" for root in frontier):
                eval_candidates = [row for row in candidates if row[2] == "EVALUATE"]
                if eval_candidates:
                    candidates = eval_candidates
            if not candidates:
                stop_reason = StopReason.NO_LEGAL_OP
                break

            if run_mode in {"until_stops", "until_credits_exhausted", "operations"}:
                partition_row = _select_partition_candidate(candidates)
                if partition_row is not None:
                    _, _, op_type, target_id, target_root = partition_row
                else:
                    reserved_counterevidence_credits = _counterevidence_probe_credits_needed()
                    if (
                        contrastive_budget_partition_enabled
                        and reserved_counterevidence_credits > 0
                        and int(credits_remaining) <= int(reserved_counterevidence_credits)
                    ):
                        deps.audit_sink.append(
                            AuditEvent(
                                "COUNTEREVIDENCE_RESERVATION_BLOCKED",
                                {
                                    "reason": "reserved_counterevidence_credits_exclusive",
                                    "required_counterevidence_credits": int(min_counterevidence_credits),
                                    "actual_counterevidence_probe_credits": int(counterevidence_probe_credits_spent),
                                    "credits_needed": int(reserved_counterevidence_credits),
                                    "credits_remaining": int(credits_remaining),
                                },
                            )
                        )
                        stop_reason = StopReason.NO_LEGAL_OP
                        break
                    by_root: Dict[str, Tuple[float, str, str, str, RootHypothesis]] = {
                        row[4].root_id: row for row in candidates
                    }
                    selected_row: Optional[Tuple[float, str, str, str, RootHypothesis]] = None
                    for offset in range(len(frontier)):
                        idx = (rr_index + offset) % len(frontier)
                        root = frontier[idx]
                        row = by_root.get(root.root_id)
                        if row is not None:
                            selected_row = row
                            rr_index = (idx + 1) % len(frontier)
                            break
                    if selected_row is None:
                        stop_reason = StopReason.NO_LEGAL_OP
                        break
                    _, _, op_type, target_id, target_root = selected_row
            else:
                candidates.sort(key=lambda row: (-row[0], row[1], row[3]))
                _, _, op_type, target_id, target_root = candidates[0]

            selected_pair_target_key = ""
            if bool(pair_target_context_plan):
                planned_root_id = str(pair_target_context_plan.get("root_id", "")).strip()
                planned_target_id = str(pair_target_context_plan.get("target_id", "")).strip()
                planned_pair_key = str(pair_target_context_plan.get("pair_key", "")).strip()
                if (
                    str(op_type).strip().upper() == "EVALUATE"
                    and planned_root_id == str(target_root.root_id).strip()
                    and planned_target_id == str(target_id).strip()
                    and planned_pair_key
                ):
                    selected_pair_target_key = planned_pair_key

            selected_counterevidence_probe = (
                bool(counterevidence_probe_plan)
                and str(counterevidence_probe_plan.get("target_id", "")).strip() == str(target_id).strip()
                and str(op_type).strip().upper() == "EVALUATE"
            )
            before = credits_remaining
            credits_remaining -= 1
            total_credits_spent += 1
            target_root.credits_spent += 1

            actual_op_type = op_type
            if op_type == "DECOMPOSE":
                if ":" in target_id:
                    slot_decomp = deps.decomposer.decompose(target_id)
                    decomposed = _apply_node_decomposition(deps, target_id, slot_decomp, nodes)
                    if decomposed:
                        parent_node = nodes.get(target_id)
                        if parent_node and parent_node.decomp_type in {"AND", "OR"}:
                            parent_node.k, k_details = _propagate_parent_k(parent_node, nodes)
                            deps.audit_sink.append(
                                AuditEvent(
                                    "PARENT_K_PROPAGATED",
                                    {
                                        "node_key": parent_node.node_key,
                                        "k_parent": float(parent_node.k),
                                        **k_details,
                                    },
                                )
                            )
                        for event in _propagate_parent_updates(target_id, nodes):
                            deps.audit_sink.append(event)
                        _recompute_root_confidence(target_root, required_slot_keys, required_slot_roles, nodes)
                    else:
                        # If slot decomposition is unavailable, evaluate directly rather than
                        # burning credit on a no-op decomposition.
                        node = nodes.get(target_id)
                        if node and not node.assessed:
                            evaluate_node(target_root, target_id, target_pair_key=selected_pair_target_key or None)
                            credits_evaluated += 1
                            actual_op_type = "EVALUATE"
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
                record_op(actual_op_type, target_id, before, credits_remaining)
            else:
                evaluate_node(target_root, target_id, target_pair_key=selected_pair_target_key or None)
                credits_evaluated += 1
                record_op("EVALUATE", target_id, before, credits_remaining)

            if (
                hunter_judge_split_enabled
                and hunter_search_loan_remaining > 0
                and hunter_target_root_id
                and str(target_root.root_id).strip() == str(hunter_target_root_id).strip()
            ):
                hunter_search_loan_remaining = max(0, int(hunter_search_loan_remaining) - 1)

            if selected_counterevidence_probe and actual_op_type == "EVALUATE":
                counterevidence_probe_credits_spent += 1
                root_counterevidence_probe_counts[target_root.root_id] = int(
                    root_counterevidence_probe_counts.get(target_root.root_id, 0)
                ) + 1
                deps.audit_sink.append(
                    AuditEvent(
                        "COUNTEREVIDENCE_PROBE_CREDIT_RECORDED",
                        {
                            "root_id": target_root.root_id,
                            "target_id": target_id,
                            "reason": str(counterevidence_probe_plan.get("reason", "")),
                            "pair_key": str(counterevidence_probe_plan.get("pair_key", "")),
                            "required_counterevidence_credits": int(min_counterevidence_credits),
                            "actual_counterevidence_probe_credits": int(counterevidence_probe_credits_spent),
                            "remaining_counterevidence_probe_credits": max(
                                0,
                                int(min_counterevidence_credits) - int(counterevidence_probe_credits_spent),
                            ),
                        },
                    )
                )
            counterevidence_probe_plan = {}
            pair_target_context_plan = {}

            if run_mode == "operations" and op_limit is not None and total_credits_spent >= int(op_limit):
                stop_reason = StopReason.OP_LIMIT_REACHED
                break

            if run_mode == "until_credits_exhausted":
                if credits_remaining <= 0:
                    stop_reason = StopReason.CREDITS_EXHAUSTED
                    break
                continue

    if (
        pair_adjudication_queue_enabled
        and bool(mece_assessment.get("strict"))
        and pair_catalog
    ):
        pair_adjudication_snapshot = dict(_current_pair_adjudication_snapshot())
        pairwise_unresolved_pairs = list(pair_adjudication_snapshot.get("unresolved_pairs", []))

    if (
        closure_active_set_adjudication_required
        and bool(mece_assessment.get("strict"))
        and pair_catalog
    ):
        closure_adjudication_snapshot = dict(_current_closure_adjudication_snapshot())
        pairwise_unresolved_pairs = list(closure_adjudication_snapshot.get("unresolved_pairs", []))

    if stop_reason in {StopReason.NO_LEGAL_OP, StopReason.CREDITS_EXHAUSTED} and _is_epistemic_limit(tau_effective):
        stop_reason = StopReason.EPISTEMICALLY_EXHAUSTED
        deps.audit_sink.append(
            AuditEvent(
                "EPISTEMIC_LIMIT_REACHED",
                {
                    "mode": reasoning_mode,
                    "tau_config": float(tau_config),
                    "tau_effective": float(tau_effective),
                },
            )
        )
        next_steps = _generate_next_steps(tau_effective)
        if pairwise_unresolved_pairs:
            deps.audit_sink.append(
                AuditEvent(
                    "PAIRWISE_ADJUDICATION_INCOMPLETE",
                    {
                        "pairwise_coverage_ratio": float(
                            _pairwise_resolution_ratio(pair_catalog_set)
                            if pair_catalog_set
                            else pairwise_coverage_ratio
                        ),
                        "min_discriminator_coverage_ratio": float(min_discriminator_coverage_ratio),
                        "unresolved_pairs_count": len(pairwise_unresolved_pairs),
                        "unresolved_pairs": list(pairwise_unresolved_pairs),
                    },
                )
            )
            for pair in pairwise_unresolved_pairs:
                root_a, root_b = pair.split("|", 1) if "|" in pair else (pair, "")
                next_steps.append(
                    {
                        "root_pair": pair,
                        "root_a": root_a,
                        "root_b": root_b,
                        "reason": "pairwise_adjudication_incomplete",
                    }
                )
        if reasoning_profile == "causal_investigation" and "process_trace_integrity" in required_slot_keys:
            missing_roots: List[str] = []
            for root in _named_roots_in_order():
                node_key = root.obligations.get("process_trace_integrity")
                node = nodes.get(node_key) if node_key else None
                if node is None or float(node.k) < float(tau_effective):
                    missing_roots.append(root.root_id)
            if missing_roots:
                deps.audit_sink.append(
                    AuditEvent(
                        "PROCESS_TRACE_SLOT_REQUIRED",
                        {
                            "slot_key": "process_trace_integrity",
                            "missing_roots": list(missing_roots),
                            "tau_effective": float(tau_effective),
                        },
                    )
                )
        deps.audit_sink.append(
            AuditEvent(
                "NEXT_STEPS_GENERATED",
                {
                    "mode": reasoning_mode,
                    "tau_effective": float(tau_effective),
                    "count": len(next_steps),
                    "next_steps": list(next_steps),
                },
            )
        )
        next_steps_event_emitted = True

    def _elevate_underdetermination_mass(min_floor: float, source: str = "") -> Tuple[float, float]:
        und_before = float(hypothesis_set.ledger.get(H_UND_ID, 0.0))
        noa_mass = float(hypothesis_set.ledger.get(H_NOA_ID, 0.0))
        active_named_ids = _active_named_root_ids()
        retired_named_ids = [root_id for root_id in named_root_ids if root_id not in set(active_named_ids)]
        retired_sum = sum(max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in retired_named_ids)
        named_values = [max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in active_named_ids]
        top_named = max(named_values) if named_values else 0.0
        dynamic_floor = _dynamic_abstention_floor(und_before, minimum_floor=float(min_floor), source=source)
        und_target = max(float(min_floor), float(dynamic_floor), und_before, top_named + 0.01)
        und_target = _clip(und_target, 0.0, max(0.0, 1.0 - noa_mass))

        named_total = sum(named_values)
        named_remaining = max(0.0, 1.0 - noa_mass - und_target - retired_sum)
        if active_named_ids:
            if named_total <= 1e-12:
                per_root = named_remaining / float(len(active_named_ids))
                for root_id in active_named_ids:
                    hypothesis_set.ledger[root_id] = per_root
            else:
                scale = named_remaining / named_total
                for root_id in active_named_ids:
                    hypothesis_set.ledger[root_id] = max(
                        0.0,
                        float(hypothesis_set.ledger.get(root_id, 0.0)) * scale,
                    )
        hypothesis_set.ledger[H_UND_ID] = und_target
        active_sum = sum(float(hypothesis_set.ledger.get(root_id, 0.0)) for root_id in active_named_ids)
        named_sum = float(retired_sum) + float(active_sum)
        hypothesis_set.ledger[H_NOA_ID] = max(0.0, 1.0 - float(hypothesis_set.ledger[H_UND_ID]) - float(named_sum))
        return und_before, float(hypothesis_set.ledger.get(H_UND_ID, 0.0))

    def _select_decision_active_set(
        ranked_named: List[Tuple[float, str]],
    ) -> List[str]:
        return _select_ranked_active_set(
            ranked_named,
            enabled=decision_active_set_enabled,
            requested_size=decision_active_set_size,
            mass_ratio=decision_active_set_mass_ratio,
            pair_budget=pair_adjudication_pair_budget,
        )

    def _apply_pair_resolution_mass_update(source: str = "decision_contract") -> None:
        if not pair_resolution_engine_enabled:
            return
        if float(pair_resolution_winner_update_gain) <= 0.0:
            return
        active_named_ids = _active_named_root_ids()
        if not active_named_ids or not pair_catalog_set:
            return

        support_by_root: Dict[str, float] = {root_id: 0.0 for root_id in active_named_ids}
        resolved_pairs = sorted(_resolved_pairs_for_scope(pair_catalog_set))
        if not resolved_pairs:
            return

        for pair in resolved_pairs:
            payload = _pair_resolution_payload(pair)
            verdict = str(payload.get("verdict", "")).strip().upper()
            strength = max(0.0, float(payload.get("strength", 0.0)))
            left_root_id = str(payload.get("left_root_id", "")).strip()
            right_root_id = str(payload.get("right_root_id", "")).strip()
            if verdict == "FAVORS_LEFT":
                if left_root_id in support_by_root:
                    support_by_root[left_root_id] += strength
                if right_root_id in support_by_root:
                    support_by_root[right_root_id] -= strength
            elif verdict == "FAVORS_RIGHT":
                if right_root_id in support_by_root:
                    support_by_root[right_root_id] += strength
                if left_root_id in support_by_root:
                    support_by_root[left_root_id] -= strength

        if all(abs(value) <= 1e-12 for value in support_by_root.values()):
            return

        noa_mass = max(0.0, float(hypothesis_set.ledger.get(H_NOA_ID, 0.0)))
        und_mass = max(0.0, float(hypothesis_set.ledger.get(H_UND_ID, 0.0)))
        retired_sum = sum(
            max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
            for root_id in named_root_ids
            if root_id not in set(active_named_ids)
        )
        named_target_total = max(0.0, 1.0 - noa_mass - und_mass - retired_sum)
        if named_target_total <= 0.0:
            return

        gain_scale = float(pair_resolution_winner_update_gain) / float(max(1, len(pair_catalog_set)))
        named_before = {
            root_id: max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
            for root_id in active_named_ids
        }
        provisional = {
            root_id: max(0.0, named_before[root_id] + gain_scale * float(support_by_root.get(root_id, 0.0)))
            for root_id in active_named_ids
        }
        provisional_total = sum(provisional.values())
        if provisional_total <= 1e-12:
            per_root = named_target_total / float(len(active_named_ids))
            named_after = {root_id: per_root for root_id in active_named_ids}
        else:
            scale = named_target_total / provisional_total
            named_after = {
                root_id: max(0.0, float(provisional[root_id]) * scale)
                for root_id in active_named_ids
            }

        for root_id in active_named_ids:
            hypothesis_set.ledger[root_id] = float(named_after[root_id])
            log_ledger[root_id] = _safe_log(float(named_after[root_id]))

        deps.audit_sink.append(
            AuditEvent(
                "PAIR_RESOLUTION_LEDGER_UPDATE_APPLIED",
                {
                    "source": source,
                    "pair_resolution_engine_enabled": bool(pair_resolution_engine_enabled),
                    "pair_resolution_winner_update_gain": float(pair_resolution_winner_update_gain),
                    "resolved_pair_count": len(resolved_pairs),
                    "support_by_root": dict(support_by_root),
                    "named_before": dict(named_before),
                    "named_after": dict(named_after),
                },
            )
        )

    def _story_components_for_root(root_id: str) -> List[str]:
        raw_components = policy_map.get("contender_story_components")
        if isinstance(raw_components, dict):
            row = raw_components.get(root_id)
            if isinstance(row, (list, tuple, set)):
                cleaned = [str(item).strip() for item in row if str(item).strip()]
                if cleaned:
                    return cleaned
        token = str(root_id).strip()
        if token.startswith("CS__"):
            parts = [part.strip() for part in token.split("__") if part.strip()]
            if len(parts) >= 2:
                return parts[1:]
        return [token] if token else []

    def _apply_compositional_story_regularization(source: str = "post_loop") -> None:
        if contender_space_mode != "compositional_stories":
            return
        story_root_ids = sorted([root_id for root_id in named_root_ids if str(root_id).startswith("CS__")])
        if not story_root_ids:
            return
        if not compositional_regularization_enabled and not joint_support_evidence_by_story:
            return

        noa_mass = max(0.0, float(hypothesis_set.ledger.get(H_NOA_ID, 0.0)))
        und_mass = max(0.0, float(hypothesis_set.ledger.get(H_UND_ID, 0.0)))
        named_target_total = max(0.0, 1.0 - noa_mass - und_mass)
        if named_target_total <= 0.0:
            return

        score_rows: List[Dict[str, object]] = []
        for story_id in story_root_ids:
            components = _story_components_for_root(story_id)
            cardinality = max(1, len(components))
            base_score = float(joint_support_evidence_by_story.get(story_id, hypothesis_set.ledger.get(story_id, 0.0)))
            complexity_penalty = (
                float(compositional_complexity_penalty_lambda) * float(max(0, cardinality - 1))
                if compositional_regularization_enabled
                else 0.0
            )
            adjusted_score = max(0.0, float(base_score) - float(complexity_penalty))
            score_rows.append(
                {
                    "story_id": story_id,
                    "components": list(components),
                    "cardinality": int(cardinality),
                    "base_score": float(base_score),
                    "complexity_penalty": float(complexity_penalty),
                    "adjusted_score": float(adjusted_score),
                }
            )

        if not score_rows:
            return
        deps.audit_sink.append(
            AuditEvent(
                "COMPOSITIONAL_STORY_SCORED",
                {
                    "source": source,
                    "story_scores": list(score_rows),
                },
            )
        )
        if compositional_regularization_enabled:
            deps.audit_sink.append(
                AuditEvent(
                    "COMPOSITIONAL_STORY_REGULARIZATION_APPLIED",
                    {
                        "source": source,
                        "lambda_complexity_penalty": float(compositional_complexity_penalty_lambda),
                        "story_scores": list(score_rows),
                    },
                )
            )

        adjusted_total = sum(float(row.get("adjusted_score", 0.0)) for row in score_rows)
        if adjusted_total <= 1e-12:
            per_story = named_target_total / float(len(score_rows))
            story_masses = {str(row.get("story_id", "")): float(per_story) for row in score_rows}
        else:
            story_masses = {
                str(row.get("story_id", "")): named_target_total * float(row.get("adjusted_score", 0.0)) / adjusted_total
                for row in score_rows
            }

        for story_id, mass in story_masses.items():
            hypothesis_set.ledger[story_id] = float(max(0.0, mass))

        if singleton_stories_explicit_contenders:
            for root_id in named_root_ids:
                if str(root_id).startswith("CS__"):
                    continue
                hypothesis_set.ledger[root_id] = 0.0

        for root_id in named_root_ids:
            log_ledger[root_id] = _safe_log(float(hypothesis_set.ledger.get(root_id, 0.0)))

    _apply_pair_resolution_mass_update("post_loop_decision_phase")
    _apply_compositional_story_regularization("post_loop_decision_phase")

    observed_pairwise_coverage_ratio = (
        len(observed_discriminator_pairs.intersection(pair_catalog_set)) / float(len(pair_catalog_set))
        if pair_catalog_set
        else float(pairwise_coverage_ratio)
    )
    resolved_pairwise_coverage_ratio = (
        _pairwise_resolution_ratio(pair_catalog_set)
        if pair_catalog_set
        else float(pairwise_coverage_ratio)
    )
    decision_pairwise_coverage_ratio = (
        float(resolved_pairwise_coverage_ratio)
        if pair_resolution_engine_enabled
        else float(observed_pairwise_coverage_ratio)
    )
    if (
        not pair_resolution_engine_enabled
        and not typed_discriminator_evidence_required
        and strict_contrastive_updates_required
    ):
        decision_pairwise_coverage_ratio = max(
            float(decision_pairwise_coverage_ratio),
            float(pairwise_coverage_ratio),
        )
    pairwise_coverage_ratio = float(decision_pairwise_coverage_ratio)
    decision_contract_status = "NOT_EVALUATED"
    decision_named_root_ids = _active_named_root_ids()

    if decision_contract_enabled and decision_named_root_ids:
        ranked_named = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in decision_named_root_ids),
            key=lambda row: (-row[0], row[1]),
        )
        winner_prob, winner_root_id = ranked_named[0] if ranked_named else (0.0, "")
        runner_up_prob, runner_up_root_id = ranked_named[1] if len(ranked_named) >= 2 else (0.0, "")
        winner_margin = float(winner_prob) - float(runner_up_prob) if runner_up_root_id else 1.0

        pairwise_scope = "global"
        active_set_roots: List[str] = []
        pair_scope_catalog_theoretical = list(pair_catalog_theoretical)
        pair_scope_catalog, pair_scope_meta = _feasible_pair_scope(pair_scope_catalog_theoretical)
        pair_scope_set = set(pair_scope_catalog)
        pair_scope_observed_ratio = float(observed_pairwise_coverage_ratio)
        pair_scope_resolved_ratio = float(resolved_pairwise_coverage_ratio)
        pair_scope_effective_ratio = float(decision_pairwise_coverage_ratio)

        candidate_active_roots = _select_decision_active_set(ranked_named)
        if len(candidate_active_roots) >= 2:
            active_set_roots = list(candidate_active_roots)
            pairwise_scope = "active_set"
            pair_scope_catalog_theoretical = _pair_catalog(active_set_roots)
            pair_scope_catalog, pair_scope_meta = _feasible_pair_scope(pair_scope_catalog_theoretical)
            pair_scope_set = set(pair_scope_catalog)
            observed_pair_scope = sorted(observed_discriminator_pairs.intersection(pair_scope_set))
            resolved_pair_scope = sorted(_resolved_pairs_for_scope(pair_scope_set))
            pair_scope_observed_ratio = (
                len(observed_pair_scope) / float(len(pair_scope_catalog))
                if pair_scope_catalog
                else 1.0
            )
            pair_scope_resolved_ratio = (
                len(resolved_pair_scope) / float(len(pair_scope_catalog))
                if pair_scope_catalog
                else 1.0
            )
            pair_scope_effective_ratio = (
                float(pair_scope_resolved_ratio)
                if pair_resolution_engine_enabled
                else float(pair_scope_observed_ratio)
            )
            if (
                not pair_resolution_engine_enabled
                and not typed_discriminator_evidence_required
                and strict_contrastive_updates_required
            ):
                pair_scope_effective_ratio = max(
                    float(pair_scope_effective_ratio),
                    float(pairwise_coverage_ratio),
                )
            deps.audit_sink.append(
                AuditEvent(
                    "DECISION_ACTIVE_SET_SELECTED",
                    {
                        "active_set_roots": list(active_set_roots),
                        "active_set_pair_count": len(pair_scope_catalog),
                        "active_set_theoretical_pair_count": len(pair_scope_catalog_theoretical),
                        "pair_budget": int(pair_scope_meta.get("pair_budget", pair_adjudication_pair_budget)),
                        "budget_feasible_enabled": bool(
                            pair_scope_meta.get("budget_feasible_enabled", False)
                        ),
                        "active_set_pairs": list(pair_scope_catalog),
                        "observed_active_set_pair_count": len(observed_pair_scope),
                        "resolved_active_set_pair_count": len(resolved_pair_scope),
                        "observed_active_set_pairwise_coverage_ratio": float(pair_scope_observed_ratio),
                        "resolved_active_set_pairwise_coverage_ratio": float(pair_scope_resolved_ratio),
                        "effective_active_set_pairwise_coverage_ratio": float(pair_scope_effective_ratio),
                        "min_pairwise_coverage_ratio": float(decision_min_pairwise_coverage_ratio),
                        "pair_resolution_engine_enabled": bool(pair_resolution_engine_enabled),
                    },
                )
            )

        failing_conditions: List[str] = []
        if pair_scope_catalog and float(pair_scope_effective_ratio) + 1e-12 < float(decision_min_pairwise_coverage_ratio):
            failing_conditions.append("pairwise_coverage_below_min")
        if float(winner_margin) + 1e-12 < float(decision_min_winner_margin):
            failing_conditions.append("winner_margin_below_min")
        if (
            decision_require_loser_falsification
            and runner_up_root_id
            and int(root_falsification_counts.get(runner_up_root_id, 0)) <= 0
        ):
            failing_conditions.append("loser_falsification_missing")
        if (
            decision_require_counterevidence_probe
            and runner_up_root_id
            and int(root_discriminator_eval_counts.get(runner_up_root_id, 0)) <= 0
        ):
            failing_conditions.append("counterevidence_probe_missing")

        if contrastive_budget_partition_enabled:
            if int(contrastive_discriminator_credits_spent) < int(min_contrastive_discriminator_credits):
                failing_conditions.append("contrastive_budget_floor_unmet")
                deps.audit_sink.append(
                    AuditEvent(
                        "CONTRASTIVE_BUDGET_FLOOR_UNMET",
                        {
                            "required_contrastive_discriminator_credits": int(min_contrastive_discriminator_credits),
                            "actual_contrastive_discriminator_credits": int(contrastive_discriminator_credits_spent),
                        },
                    )
                )
            if int(counterevidence_probe_credits_spent) < int(min_counterevidence_credits):
                failing_conditions.append("counterevidence_budget_floor_unmet")
                deps.audit_sink.append(
                    AuditEvent(
                        "COUNTEREVIDENCE_BUDGET_FLOOR_UNMET",
                        {
                            "required_counterevidence_credits": int(min_counterevidence_credits),
                            "actual_counterevidence_credits": int(counterevidence_probe_credits_spent),
                            "actual_counterevidence_probe_credits": int(counterevidence_probe_credits_spent),
                            "actual_counterevidence_falsification_credits": int(
                                counterevidence_falsification_credits_spent
                            ),
                        },
                    )
                )

        if strict_contrastive_updates_required and int(strict_signal_counts.get("discriminative", 0)) <= 0:
            failing_conditions.append("no_discriminative_updates")

        if failing_conditions:
            decision_contract_status = "FAILED"
            h_und_before, h_und_after = _elevate_underdetermination_mass(
                0.0,
                source="decision_contract_failure",
            )
            if not next_steps:
                next_steps = _generate_next_steps(tau_effective)
            if pair_scope_catalog:
                for pair in pair_scope_catalog:
                    if not any(
                        isinstance(step, dict) and str(step.get("root_pair", "")).strip() == pair for step in next_steps
                    ):
                        root_a, root_b = pair.split("|", 1)
                        next_steps.append(
                            {
                                "root_pair": pair,
                                "root_a": root_a,
                                "root_b": root_b,
                                "reason": "decision_contract_failure",
                            }
                        )
            deps.audit_sink.append(
                AuditEvent(
                    "DECISION_CONTRACT_FAILED",
                    {
                        "winner_root_id": winner_root_id,
                        "runner_up_root_id": runner_up_root_id,
                        "winner_margin": float(winner_margin),
                        "min_winner_margin": float(decision_min_winner_margin),
                        "pairwise_scope": pairwise_scope,
                        "active_set_roots": list(active_set_roots),
                        "active_set_pair_count": len(pair_scope_catalog) if pairwise_scope == "active_set" else 0,
                        "active_set_theoretical_pair_count": (
                            len(pair_scope_catalog_theoretical) if pairwise_scope == "active_set" else 0
                        ),
                        "pair_budget": int(pair_scope_meta.get("pair_budget", pair_adjudication_pair_budget)),
                        "budget_feasible_enabled": bool(
                            pair_scope_meta.get("budget_feasible_enabled", False)
                        ),
                        "observed_pairwise_coverage_ratio": float(observed_pairwise_coverage_ratio),
                        "resolved_pairwise_coverage_ratio": float(resolved_pairwise_coverage_ratio),
                        "effective_pairwise_coverage_ratio": float(pair_scope_effective_ratio),
                        "effective_active_set_pairwise_coverage_ratio": float(pair_scope_effective_ratio),
                        "min_pairwise_coverage_ratio": float(decision_min_pairwise_coverage_ratio),
                        "pair_resolution_engine_enabled": bool(pair_resolution_engine_enabled),
                        "failing_conditions": sorted(set(failing_conditions)),
                        "h_und_before": float(h_und_before),
                        "h_und_after": float(h_und_after),
                    },
                )
            )
            if stop_reason == StopReason.FRONTIER_CONFIDENT:
                stop_reason = StopReason.CLOSURE_GATES_UNMET
            if not next_steps_event_emitted:
                deps.audit_sink.append(
                    AuditEvent(
                        "NEXT_STEPS_GENERATED",
                        {
                            "mode": reasoning_mode,
                            "tau_effective": float(tau_effective),
                            "count": len(next_steps),
                            "next_steps": list(next_steps),
                        },
                    )
                )
                next_steps_event_emitted = True
        else:
            decision_contract_status = "PASSED"
            deps.audit_sink.append(
                AuditEvent(
                    "DECISION_CONTRACT_PASSED",
                    {
                        "winner_root_id": winner_root_id,
                        "runner_up_root_id": runner_up_root_id,
                        "winner_margin": float(winner_margin),
                        "pairwise_scope": pairwise_scope,
                        "active_set_roots": list(active_set_roots),
                        "active_set_pair_count": len(pair_scope_catalog) if pairwise_scope == "active_set" else 0,
                        "active_set_theoretical_pair_count": (
                            len(pair_scope_catalog_theoretical) if pairwise_scope == "active_set" else 0
                        ),
                        "pair_budget": int(pair_scope_meta.get("pair_budget", pair_adjudication_pair_budget)),
                        "budget_feasible_enabled": bool(
                            pair_scope_meta.get("budget_feasible_enabled", False)
                        ),
                        "observed_pairwise_coverage_ratio": float(observed_pairwise_coverage_ratio),
                        "resolved_pairwise_coverage_ratio": float(resolved_pairwise_coverage_ratio),
                        "effective_pairwise_coverage_ratio": float(pair_scope_effective_ratio),
                        "effective_active_set_pairwise_coverage_ratio": float(pair_scope_effective_ratio),
                        "min_pairwise_coverage_ratio": float(decision_min_pairwise_coverage_ratio),
                        "pair_resolution_engine_enabled": bool(pair_resolution_engine_enabled),
                    },
                )
            )

    if (
        bool(mece_assessment.get("strict"))
        and strict_contrastive_updates_required
        and pair_catalog
        and not pairwise_unresolved_pairs
    ):
        active_named_ids = _active_named_root_ids()
        ranked_named = sorted(
            ((float(hypothesis_set.ledger.get(root_id, 0.0)), root_id) for root_id in active_named_ids),
            key=lambda row: (-row[0], row[1]),
        )
        if len(ranked_named) >= 2:
            top_prob = float(ranked_named[0][0])
            second_prob = float(ranked_named[1][0])
            top_margin = abs(top_prob - second_prob)
            if (
                top_margin <= max(float(request.config.epsilon), 1e-6)
                and int(strict_signal_counts.get("discriminative", 0)) > 0
            ):
                noa_mass = float(hypothesis_set.ledger.get(H_NOA_ID, 0.0))
                und_current = float(hypothesis_set.ledger.get(H_UND_ID, 0.0))
                und_target = _dynamic_abstention_floor(
                    und_current,
                    minimum_floor=und_current,
                    source="underdetermination_certified",
                )
                retired_named_ids = [root_id for root_id in named_root_ids if root_id not in set(active_named_ids)]
                retired_sum = sum(
                    max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0)))
                    for root_id in retired_named_ids
                )
                top_named_current = max(
                    (max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in active_named_ids),
                    default=0.0,
                )
                und_target = max(float(und_target), float(top_named_current) + 0.01)
                und_target = _clip(und_target, 0.0, max(0.0, 1.0 - noa_mass))
                named_remaining = max(0.0, 1.0 - noa_mass - und_target - retired_sum)
                named_total = sum(
                    max(0.0, float(hypothesis_set.ledger.get(root_id, 0.0))) for root_id in active_named_ids
                )
                if active_named_ids:
                    if named_total <= 1e-12:
                        per_root = named_remaining / float(len(active_named_ids))
                        for root_id in active_named_ids:
                            hypothesis_set.ledger[root_id] = per_root
                    else:
                        scale = named_remaining / named_total
                        for root_id in active_named_ids:
                            hypothesis_set.ledger[root_id] = max(
                                0.0,
                                float(hypothesis_set.ledger.get(root_id, 0.0)) * scale,
                            )
                hypothesis_set.ledger[H_UND_ID] = und_target
                active_named_sum = sum(float(hypothesis_set.ledger.get(root_id, 0.0)) for root_id in active_named_ids)
                named_sum = float(active_named_sum) + float(retired_sum)
                hypothesis_set.ledger[H_NOA_ID] = max(0.0, 1.0 - named_sum - float(hypothesis_set.ledger[H_UND_ID]))

                deps.audit_sink.append(
                    AuditEvent(
                        "UNDERDETERMINATION_CERTIFIED",
                        {
                            "pairwise_coverage_ratio": float(decision_pairwise_coverage_ratio),
                            "observed_pairwise_coverage_ratio": float(observed_pairwise_coverage_ratio),
                            "resolved_pairwise_coverage_ratio": float(resolved_pairwise_coverage_ratio),
                            "unresolved_pairs_count": len(pairwise_unresolved_pairs),
                            "discriminative_updates": int(strict_signal_counts.get("discriminative", 0)),
                            "non_discriminative_updates": int(strict_signal_counts.get("non_discriminative", 0)),
                            "top_margin": float(top_margin),
                            "epsilon": float(request.config.epsilon),
                            "h_und_before": float(und_current),
                            "h_und_after": float(hypothesis_set.ledger.get(H_UND_ID, 0.0)),
                            "pairwise_unresolved_ratio": float(_pairwise_unresolved_ratio()),
                            "contradiction_density": float(_contradiction_density()),
                        },
                    )
                )

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

    for root in hypothesis_set.roots.values():
        _apply_root_confidence_policies(root)
    _emit_frame_inadequate_anomaly_once()

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

    dual_outputs_payload: Dict[str, object] = {}
    if dual_outputs_enabled:
        selection_root_ids = _active_named_root_ids()
        all_named_assessed = True
        for root_id in selection_root_ids:
            root = hypothesis_set.roots.get(root_id)
            if root is None:
                continue
            for slot_key in required_slot_keys:
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if node is None or not bool(node.assessed):
                    all_named_assessed = False
                    break
            if not all_named_assessed:
                break

        def _selection_score(root_id: str) -> float:
            if not all_named_assessed:
                if isinstance(request.initial_ledger, dict) and root_id in request.initial_ledger:
                    return float(request.initial_ledger.get(root_id, 0.0))
                return 0.0
            root = hypothesis_set.roots.get(root_id)
            if not root:
                return float(hypothesis_set.ledger.get(root_id, 0.0))
            weighted_total = 0.0
            weight = 0.0
            for slot_key in required_slot_keys:
                node_key = root.obligations.get(slot_key)
                node = nodes.get(node_key) if node_key else None
                if not node or not bool(node.assessed):
                    continue
                slot_weight = max(0.01, float(node.k))
                weighted_total += float(node.p) * slot_weight
                weight += slot_weight
            if weight > 0.0:
                return weighted_total / weight
            return float(hypothesis_set.ledger.get(root_id, 0.0))

        selection_ranking = sorted(
            ((float(_selection_score(root_id)), root_id) for root_id in selection_root_ids),
            key=lambda row: (-row[0], row[1]),
        )
        selection_top_root_id = str(selection_ranking[0][1]) if selection_ranking else ""
        selection_top_prob = float(selection_ranking[0][0]) if selection_ranking else 0.0
        selection_payload: Dict[str, object] = {
            "required": bool(selection_output_required),
            "top_root_id": selection_top_root_id,
            "top_root_score": float(selection_top_prob),
            "ranking": [
                {"root_id": str(root_id), "score": float(score)}
                for score, root_id in selection_ranking
            ],
        }
        certification_status = "CERTIFIED"
        certification_top_root_id = selection_top_root_id
        if decision_contract_enabled and decision_contract_status != "PASSED":
            if certification_output_allows_abstention:
                certification_status = "ABSTAIN"
                certification_top_root_id = H_UND_ID
            else:
                certification_status = "FAILED"
        certification_payload: Dict[str, object] = {
            "allows_abstention": bool(certification_output_allows_abstention),
            "status": certification_status,
            "top_root_id": certification_top_root_id,
            "decision_contract_status": str(decision_contract_status),
        }
        dual_outputs_payload = {
            "selection": selection_payload,
            "certification": certification_payload,
        }
        deps.audit_sink.append(
            AuditEvent(
                "DUAL_OUTPUTS_EMITTED",
                {
                    "selection_top_root_id": selection_top_root_id,
                    "certification_status": certification_status,
                    "certification_top_root_id": certification_top_root_id,
                    "decision_contract_enabled": bool(decision_contract_enabled),
                    "decision_contract_status": str(decision_contract_status),
                },
            )
        )

    metadata: Dict[str, Any] = {"framing": request.framing} if request.framing else {}
    if profile_metadata:
        metadata.update(profile_metadata)
    if dual_outputs_payload:
        metadata["dual_outputs"] = dict(dual_outputs_payload)
    metadata["contender_space"] = {
        "status": contender_space_assessment.get("status"),
        "mode": contender_space_assessment.get("mode"),
        "explicit_mode": contender_space_assessment.get("explicit_mode"),
        "auto_expanded": contender_space_assessment.get("auto_expanded"),
        "max_story_cardinality_limit": contender_space_assessment.get("max_story_cardinality_limit"),
        "max_story_cardinality": contender_space_assessment.get("max_story_cardinality"),
        "multi_factor_story_count": contender_space_assessment.get("multi_factor_story_count"),
        "cardinality_by_root": dict(contender_space_assessment.get("cardinality_by_root", {})),
    }
    metadata["closure_adjudication"] = {
        "enabled": bool(closure_active_set_adjudication_required),
        "status": closure_adjudication_snapshot.get("status"),
        "pairwise_scope": closure_adjudication_snapshot.get("pairwise_scope"),
        "candidate_active_set_roots": list(closure_adjudication_snapshot.get("candidate_active_set_roots", [])),
        "active_set_roots": list(closure_adjudication_snapshot.get("active_set_roots", [])),
        "active_set_pair_count": int(closure_adjudication_snapshot.get("active_set_pair_count", 0)),
        "active_set_theoretical_pair_count": int(
            closure_adjudication_snapshot.get("active_set_theoretical_pair_count", 0)
        ),
        "pair_count": int(closure_adjudication_snapshot.get("pair_count", 0)),
        "theoretical_pair_count": int(closure_adjudication_snapshot.get("theoretical_pair_count", 0)),
        "pair_budget": int(closure_adjudication_snapshot.get("pair_budget", pair_adjudication_pair_budget)),
        "budget_feasible_enabled": bool(closure_adjudication_snapshot.get("budget_feasible_enabled", False)),
        "active_set_lock_enabled": bool(closure_adjudication_snapshot.get("active_set_lock_enabled", False)),
        "active_set_lock_roots": list(closure_adjudication_snapshot.get("active_set_lock_roots", [])),
        "active_set_lock_reused": bool(closure_adjudication_snapshot.get("active_set_lock_reused", False)),
        "observed_pair_count": int(closure_adjudication_snapshot.get("observed_pair_count", 0)),
        "resolved_pair_count": int(closure_adjudication_snapshot.get("resolved_pair_count", 0)),
        "resolved_pairs": list(closure_adjudication_snapshot.get("resolved_pairs", [])),
        "resolved_coverage_ratio": float(closure_adjudication_snapshot.get("resolved_coverage_ratio", 0.0)),
        "coverage_ratio": float(closure_adjudication_snapshot.get("coverage_ratio", 0.0)),
        "min_pairwise_coverage_ratio": float(
            closure_adjudication_snapshot.get("min_pairwise_coverage_ratio", closure_min_pairwise_coverage_ratio)
        ),
        "unresolved_pairs_count": int(closure_adjudication_snapshot.get("unresolved_pairs_count", 0)),
        "unresolved_pairs": list(closure_adjudication_snapshot.get("unresolved_pairs", [])),
    }
    metadata["pair_adjudication"] = {
        "enabled": bool(pair_adjudication_queue_enabled),
        "scope": pair_adjudication_snapshot.get("scope"),
        "status": pair_adjudication_snapshot.get("status"),
        "pairwise_scope": pair_adjudication_snapshot.get("pairwise_scope"),
        "candidate_active_set_roots": list(pair_adjudication_snapshot.get("candidate_active_set_roots", [])),
        "active_set_roots": list(pair_adjudication_snapshot.get("active_set_roots", [])),
        "active_set_pair_count": int(pair_adjudication_snapshot.get("active_set_pair_count", 0)),
        "active_set_theoretical_pair_count": int(pair_adjudication_snapshot.get("active_set_theoretical_pair_count", 0)),
        "pair_count": int(pair_adjudication_snapshot.get("pair_count", 0)),
        "theoretical_pair_count": int(pair_adjudication_snapshot.get("theoretical_pair_count", 0)),
        "pair_budget": int(pair_adjudication_snapshot.get("pair_budget", pair_adjudication_pair_budget)),
        "budget_feasible_enabled": bool(pair_adjudication_snapshot.get("budget_feasible_enabled", False)),
        "active_set_lock_enabled": bool(pair_adjudication_snapshot.get("active_set_lock_enabled", False)),
        "active_set_lock_roots": list(pair_adjudication_snapshot.get("active_set_lock_roots", [])),
        "active_set_lock_reused": bool(pair_adjudication_snapshot.get("active_set_lock_reused", False)),
        "active_set_lock_released": bool(pair_adjudication_snapshot.get("active_set_lock_released", False)),
        "balance_targets_enabled": bool(pair_adjudication_snapshot.get("balance_targets_enabled", False)),
        "min_targets_per_side": int(pair_adjudication_snapshot.get("min_targets_per_side", 1)),
        "bootstrap_missing_side_enabled": bool(
            pair_adjudication_snapshot.get("bootstrap_missing_side_enabled", False)
        ),
        "coverage_ratio": float(pair_adjudication_snapshot.get("coverage_ratio", 0.0)),
        "unresolved_pairs_count": int(pair_adjudication_snapshot.get("unresolved_pairs_count", 0)),
        "unresolved_pairs": list(pair_adjudication_snapshot.get("unresolved_pairs", [])),
        "observed_pairs": list(pair_adjudication_snapshot.get("observed_pairs", [])),
        "resolved_pair_count": int(pair_adjudication_snapshot.get("resolved_pair_count", 0)),
        "resolved_pairs": list(pair_adjudication_snapshot.get("resolved_pairs", [])),
    }
    metadata["pair_resolution"] = {
        "engine_enabled": bool(pair_resolution_engine_enabled),
        "min_directional_margin": float(pair_resolution_min_directional_margin),
        "min_directional_evidence_count": int(pair_resolution_min_directional_evidence_count),
        "max_contradiction_density": float(pair_resolution_max_contradiction_density),
        "winner_update_gain": float(pair_resolution_winner_update_gain),
        "resolved_pair_count": int(len(_resolved_pairs_for_scope(pair_catalog_set))),
        "pair_count": int(len(pair_catalog_set)),
        "coverage_ratio": float(_pairwise_resolution_ratio(pair_catalog_set)) if pair_catalog_set else 1.0,
    }
    metadata["directional_typed_linker"] = {
        "enabled": bool(directional_typed_evidence_linker_enabled),
        "conflict_policy": str(directional_typed_evidence_conflict_policy),
        "tracked_pair_count": int(len(pair_directional_evidence_links)),
    }
    metadata["contender_retirement"] = {
        "enabled": bool(contender_retirement_enabled),
        "retired_root_ids": sorted(retired_root_ids),
        "retired_roots": dict(retired_root_reasons),
        "min_decisive_losses": int(contender_retirement_min_decisive_losses),
        "min_resolved_pairs": int(contender_retirement_min_resolved_pairs),
        "min_pair_margin": float(contender_retirement_min_pair_margin),
        "min_pair_strength": float(contender_retirement_min_pair_strength),
        "require_no_decisive_wins": bool(contender_retirement_require_no_decisive_wins),
        "mass_floor": float(contender_retirement_mass_floor),
        "preserve_top_n": int(contender_retirement_preserve_top_n),
    }
    metadata["abstention"] = {
        "dynamic_enabled": bool(dynamic_abstention_mass_enabled),
        "v2_enabled": bool(dynamic_abstention_v2_enabled),
        "fixed_dominant_floor_enabled": bool(fixed_abstention_dominant_floor_enabled),
        "mass_minimum": float(dynamic_abstention_mass_minimum),
        "mass_maximum": float(dynamic_abstention_mass_maximum),
        "weights": {
            "unresolved_pair": float(dynamic_abstention_unresolved_pair_weight),
            "contradiction_density": float(dynamic_abstention_contradiction_density_weight),
            "non_discriminative": float(dynamic_abstention_non_discriminative_weight),
            "frame_adequacy": float(dynamic_abstention_frame_adequacy_weight),
        },
        "unresolved_pair_ratio": float(_pairwise_unresolved_ratio()),
        "contradiction_density": float(_contradiction_density()),
        "frame_adequacy_gap_ratio": float(_frame_adequacy_gap_ratio()),
    }
    metadata["counterevidence_budget"] = {
        "contrastive_budget_partition_enabled": bool(contrastive_budget_partition_enabled),
        "required_probe_credits": int(min_counterevidence_credits),
        "probe_credits_spent": int(counterevidence_probe_credits_spent),
        "falsification_credits_spent": int(counterevidence_falsification_credits_spent),
        "remaining_probe_credits": max(0, int(min_counterevidence_credits) - int(counterevidence_probe_credits_spent)),
    }
    metadata["quote_fidelity"] = {
        "gate_mode": quote_fidelity_gate_mode,
    }
    if next_steps:
        metadata["next_steps"] = list(next_steps)

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
        metadata=metadata,
    )
