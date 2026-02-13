from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .config import corpus_root, spec_root
from .provenance import collect_provenance
from .registry import Registry
from .run import run_case


DEFAULT_METHODS: tuple[str, ...] = ("abductio", "logodds", "checklist", "prior")
VALID_METHODS = set(DEFAULT_METHODS)
LOCKED_POLICY_REQUIRED_CASE_IDS: frozenset[str] = frozenset({"Boeing_737-8AS_9H-QAA_12-25"})

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "with",
}


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    description: str
    history_fraction: float
    fallback_fraction: float


@dataclass(frozen=True)
class RootContext:
    named_roots: List[str]
    all_roots: List[str]
    statements: Dict[str, str]


def _resolve_locked_policy_profile(profile_id: str | None) -> tuple[str | None, Dict[str, Any] | None]:
    key = str(profile_id or "").strip()
    if not key:
        return None, None
    if key == "boeing_inference_v1":
        profile_path = Path(__file__).resolve().parents[4] / "case_studies" / "boeing_inference_v1.policy.json"
        if not profile_path.exists():
            raise ValueError(f"Locked profile file not found: {profile_path}")
        policy = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise ValueError(f"Locked profile is not an object: {profile_path}")
        return key, policy
    raise ValueError(f"Unknown locked policy profile: {key}")


DEFAULT_STAGE_SPECS: tuple[StageSpec, ...] = (
    StageSpec(
        stage_id="T0_PRELIM",
        description="Synopsis only (proxy for first public bulletin facts)",
        history_fraction=0.0,
        fallback_fraction=0.25,
    ),
    StageSpec(
        stage_id="T1_EARLY",
        description="Synopsis plus early factual narrative",
        history_fraction=1.0 / 3.0,
        fallback_fraction=0.50,
    ),
    StageSpec(
        stage_id="T2_INTERIM",
        description="Synopsis plus expanded factual narrative",
        history_fraction=2.0 / 3.0,
        fallback_fraction=0.75,
    ),
    StageSpec(
        stage_id="T3_PREFINAL",
        description="Pre-final factual packet (no conclusion/safety actions)",
        history_fraction=1.0,
        fallback_fraction=1.0,
    ),
)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _results_dir() -> Path:
    path = corpus_root() / "results" / "backtest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_year(date_utc: str) -> int | None:
    raw = (date_utc or "").strip()
    if len(raw) < 4:
        return None
    try:
        return int(raw[:4])
    except ValueError:
        return None


def _parse_methods(methods: Sequence[str] | None) -> List[str]:
    if not methods:
        return list(DEFAULT_METHODS)
    parsed: List[str] = []
    for value in methods:
        for part in str(value).split(","):
            name = part.strip().lower()
            if not name:
                continue
            if name not in VALID_METHODS:
                raise ValueError(f"Unknown method: {name}. Valid methods: {sorted(VALID_METHODS)}")
            if name not in parsed:
                parsed.append(name)
    if not parsed:
        raise ValueError("No methods selected")
    return parsed


def _first_n(items: Sequence[Dict[str, Any]], fraction: float) -> List[Dict[str, Any]]:
    if not items:
        return []
    count = int(math.ceil(len(items) * fraction))
    count = max(1, min(len(items), count))
    return [dict(item) for item in items[:count]]


def _first_n_indices(indices: Sequence[int], fraction: float) -> List[int]:
    if not indices:
        return []
    count = int(math.ceil(len(indices) * fraction))
    count = max(1, min(len(indices), count))
    return list(indices[:count])


def _stage_items(
    packet_items: Sequence[Dict[str, Any]],
    stage: StageSpec,
    *,
    previous_items: Sequence[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], str]:
    history_indices: List[int] = []
    synopsis_indices: List[int] = []
    other_indices: List[int] = []
    for index, item in enumerate(packet_items):
        source = str(item.get("source", "")).lower()
        if source == "history":
            history_indices.append(index)
        elif source == "synopsis":
            synopsis_indices.append(index)
        else:
            other_indices.append(index)

    if history_indices or synopsis_indices:
        selected_indices = set(synopsis_indices)
        if stage.history_fraction > 0.0:
            selected_indices.update(_first_n_indices(history_indices, stage.history_fraction))
        if stage.stage_id == "T3_PREFINAL":
            selected_indices.update(other_indices)
        if not selected_indices:
            stage_items = _first_n(packet_items, stage.fallback_fraction)
            selection_mode = "prefix_fallback"
        else:
            stage_items = [dict(packet_items[index]) for index in sorted(selected_indices)]
            selection_mode = "section_progressive"
    else:
        stage_items = _first_n(packet_items, stage.fallback_fraction)
        selection_mode = "prefix_fallback"

    if len(stage_items) < len(previous_items):
        stage_items = [dict(item) for item in previous_items]
        selection_mode = f"{selection_mode}_monotonic"
    if not stage_items and packet_items:
        stage_items = [dict(packet_items[0])]
        selection_mode = f"{selection_mode}_forced_nonempty"
    return stage_items, selection_mode


def build_stage_packets(
    evidence_packet: Mapping[str, Any],
    *,
    stage_specs: Sequence[StageSpec] = DEFAULT_STAGE_SPECS,
) -> List[Dict[str, Any]]:
    packet_items = [dict(item) for item in evidence_packet.get("items", []) if isinstance(item, dict)]
    packets: List[Dict[str, Any]] = []
    previous_items: List[Dict[str, Any]] = []
    for index, stage in enumerate(stage_specs):
        stage_items, selection_mode = _stage_items(packet_items, stage, previous_items=previous_items)
        previous_items = stage_items
        packets.append(
            {
                "case_id": str(evidence_packet.get("case_id", "")),
                "pdf_sha256": str(evidence_packet.get("pdf_sha256", "")),
                "evidence_freeze_time_utc": str(evidence_packet.get("evidence_freeze_time_utc", "")),
                "stage_id": stage.stage_id,
                "stage_index": index,
                "stage_description": stage.description,
                "stage_mode": "section_progressive_v1",
                "stage_selection_mode": selection_mode,
                "base_item_count": len(packet_items),
                "item_count": len(stage_items),
                "items": stage_items,
            }
        )
    return packets


def _resolve_snapshot_packet_path(manifest_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return manifest_dir / path


def _dedupe_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        item_id = str(item.get("id", "")).strip()
        key = item_id if item_id else json.dumps(item, sort_keys=True)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        deduped.append(dict(item))
    return deduped


def _load_snapshot_stage_packets(case_dir: Path) -> List[Dict[str, Any]]:
    manifest_path = case_dir / "snapshots" / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("snapshots", [])
    if not isinstance(entries, list) or not entries:
        return []

    packets: List[Dict[str, Any]] = []
    previous_items: List[Dict[str, Any]] = []
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            continue
        packet_ref = str(raw_entry.get("evidence_packet", "")).strip()
        if not packet_ref:
            continue
        packet_path = _resolve_snapshot_packet_path(manifest_path.parent, packet_ref)
        if not packet_path.exists():
            raise FileNotFoundError(f"Snapshot evidence packet missing: {packet_path}")
        packet_data = json.loads(packet_path.read_text(encoding="utf-8"))
        stage_items = [dict(item) for item in packet_data.get("items", []) if isinstance(item, dict)]
        stage_items = _dedupe_items(stage_items)
        selection_mode = "snapshot_manifest"
        if len(stage_items) < len(previous_items):
            stage_items = _dedupe_items([*previous_items, *stage_items])
            selection_mode = "snapshot_manifest_monotonic"
        previous_items = stage_items

        stage_id = str(raw_entry.get("stage_id", "")).strip() or f"S{index + 1}"
        stage_description = str(raw_entry.get("description", "")).strip() or f"Snapshot {index + 1}"

        packets.append(
            {
                "case_id": str(packet_data.get("case_id", "")) or case_dir.name,
                "pdf_sha256": str(packet_data.get("pdf_sha256", "")),
                "evidence_freeze_time_utc": str(
                    packet_data.get("evidence_freeze_time_utc", raw_entry.get("evidence_freeze_time_utc", ""))
                ),
                "stage_id": stage_id,
                "stage_index": index,
                "stage_description": stage_description,
                "stage_mode": "multi_document_v1",
                "stage_selection_mode": selection_mode,
                "base_item_count": len(stage_items),
                "item_count": len(stage_items),
                "snapshot_source_doc_id": str(raw_entry.get("source_doc_id", "")),
                "snapshot_evidence_packet": str(packet_path),
                "items": stage_items,
            }
        )
    return packets


def load_case_stage_packets(case_dir: Path, evidence_packet: Mapping[str, Any]) -> List[Dict[str, Any]]:
    snapshot_packets = _load_snapshot_stage_packets(case_dir)
    if snapshot_packets:
        return snapshot_packets
    return build_stage_packets(evidence_packet)


def _load_leakage_keywords() -> List[str]:
    leakage_path = spec_root() / "leakage_checks.md"
    if not leakage_path.exists():
        return []
    keywords: List[str] = []
    in_disallowed_section = False
    for raw_line in leakage_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            in_disallowed_section = line.lower().startswith("## disallowed language detector")
            continue
        if in_disallowed_section and line.startswith("-"):
            keyword = line.lstrip("- ").strip()
            if keyword:
                keywords.append(keyword.lower())
    return keywords


def _leakage_hits(stage_items: Sequence[Dict[str, Any]], keywords: Sequence[str]) -> List[str]:
    if not keywords:
        return []
    text = " ".join(str(item.get("text", "")) for item in stage_items).lower()
    return sorted({keyword for keyword in keywords if keyword in text})


def _read_answer_root(case_dir: Path) -> str:
    path = case_dir / "answer_key.md"
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        entry = line.strip()
        if entry.startswith("- oracle_root_id:"):
            return entry.split(":", 1)[1].strip()
    for line in lines:
        entry = line.strip()
        if entry.lower().startswith("label root id:"):
            return entry.split(":", 1)[1].strip()
    return ""


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_roots(ledger: Mapping[str, object]) -> tuple[List[str], float]:
    best_score: float | None = None
    winners: List[str] = []
    for root_id, raw_value in ledger.items():
        score = _safe_float(raw_value)
        if score is None:
            continue
        rid = str(root_id)
        if best_score is None or score > best_score:
            best_score = score
            winners = [rid]
        elif abs(score - best_score) <= 1e-12:
            winners.append(rid)
    winners = sorted(winners)
    return winners, float(best_score if best_score is not None else 0.0)


def _softmax(scores: Mapping[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    max_score = max(scores.values())
    shifted = {key: math.exp(value - max_score) for key, value in scores.items()}
    total = sum(shifted.values())
    if total <= 0:
        uniform = 1.0 / len(shifted)
        return {key: uniform for key in shifted}
    return {key: shifted[key] / total for key in shifted}


def _tokens(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token and token not in STOPWORDS]


def _load_root_context(case_dir: Path) -> RootContext:
    roots_path = case_dir / "roots.yaml"
    if not roots_path.exists():
        raise FileNotFoundError(f"Missing roots.yaml: {roots_path}")

    root_set_id = ""
    root_ids: List[str] = []
    for raw_line in roots_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("root_set_id:"):
            root_set_id = line.split(":", 1)[1].strip()
        if line.startswith("- id:"):
            root_ids.append(line.split(":", 1)[1].strip())

    statements: Dict[str, str] = {}
    if root_set_id:
        library_path = spec_root() / "roots_library.json"
        if library_path.exists():
            library = json.loads(library_path.read_text(encoding="utf-8"))
            root_set = library.get("root_sets", {}).get(root_set_id, {})
            for root in root_set.get("roots", []):
                root_id = str(root.get("id", "")).strip()
                if not root_id:
                    continue
                statements[root_id] = str(root.get("label", root_id)).strip()

    named_roots = [root_id for root_id in root_ids if root_id and root_id not in {"H_OTHER", "H_NOA", "H_UND"}]
    for root_id in named_roots:
        statements.setdefault(root_id, root_id)

    statements["H_NOA"] = "None of the above"
    statements["H_UND"] = "Underdetermined"
    all_roots = [*named_roots, "H_NOA", "H_UND"]
    return RootContext(named_roots=named_roots, all_roots=all_roots, statements=statements)


def _root_keywords(root_id: str, statement: str) -> set[str]:
    tokens = set(_tokens(statement))
    tokens.update(_tokens(root_id.replace("_", " ")))
    return {token for token in tokens if len(token) > 2}


def _baseline_logodds(
    stage_items: Sequence[Dict[str, Any]],
    context: RootContext,
) -> tuple[Dict[str, float], Dict[str, Any]]:
    scores = {root_id: 0.0 for root_id in context.all_roots}
    keyword_map = {
        root_id: _root_keywords(root_id, context.statements.get(root_id, root_id))
        for root_id in context.named_roots
    }

    for item in stage_items:
        tokens = set(_tokens(str(item.get("text", ""))))
        overlaps: List[tuple[str, int]] = []
        for root_id in context.named_roots:
            overlap = len(tokens.intersection(keyword_map.get(root_id, set())))
            if overlap > 0:
                overlaps.append((root_id, overlap))

        if len(overlaps) == 1:
            root_id, overlap = overlaps[0]
            scores[root_id] += 0.40 + 0.05 * min(overlap, 3)
            for other in context.named_roots:
                if other != root_id:
                    scores[other] -= 0.04
        elif len(overlaps) > 1:
            matched = {root_id for root_id, _ in overlaps}
            for root_id, overlap in overlaps:
                scores[root_id] += 0.15 + 0.03 * min(overlap, 3)
            for other in context.named_roots:
                if other not in matched:
                    scores[other] -= 0.01
            scores["H_UND"] += 0.02
        else:
            scores["H_UND"] += 0.10
            scores["H_NOA"] += 0.03

    if len(stage_items) <= 5:
        scores["H_UND"] += 0.12

    return _softmax(scores), {"method_detail": "fixed_logodds_v1"}


def _baseline_checklist(
    stage_items: Sequence[Dict[str, Any]],
    context: RootContext,
) -> tuple[Dict[str, float], Dict[str, Any]]:
    keyword_map = {
        root_id: _root_keywords(root_id, context.statements.get(root_id, root_id))
        for root_id in context.named_roots
    }

    hit_counts: Dict[str, int] = {root_id: 0 for root_id in context.named_roots}
    for item in stage_items:
        tokens = set(_tokens(str(item.get("text", ""))))
        for root_id in context.named_roots:
            if tokens.intersection(keyword_map.get(root_id, set())):
                hit_counts[root_id] += 1

    slot_support: Dict[str, int] = {}
    for root_id in context.named_roots:
        hits = hit_counts[root_id]
        support = 0
        if hits >= 1:
            support += 1
        if hits >= 2:
            support += 1
        if hits >= 3:
            support += 1
        slot_support[root_id] = support

    winner = "H_UND"
    if slot_support:
        best_support = max(slot_support.values())
        candidates = sorted([root_id for root_id, value in slot_support.items() if value == best_support])
        if best_support >= 3 and candidates:
            winner = candidates[0]

    base = 0.02
    scores = {root_id: base for root_id in context.all_roots}
    winner_mass = 0.55 if winner in {"H_UND", "H_NOA"} else 0.65
    scores[winner] += winner_mass
    if winner == "H_UND":
        scores["H_NOA"] += 0.18

    return _softmax(scores), {"method_detail": "checklist_slots_v1", "slot_support": slot_support}


def _label_to_training_root(label_root_id: str, context: RootContext) -> str | None:
    label = (label_root_id or "").strip()
    if not label:
        return None
    if label in context.all_roots:
        return label
    if label == "H_OTHER":
        return "H_UND"
    return None


def _baseline_prior(
    *,
    training_rows: Sequence[Mapping[str, str]],
    context: RootContext,
) -> tuple[Dict[str, float], Dict[str, Any]]:
    counts: Dict[str, float] = {root_id: 1.0 for root_id in context.all_roots}
    used = 0
    for row in training_rows:
        mapped = _label_to_training_root(str(row.get("label_root_id", "")), context)
        if not mapped:
            continue
        counts[mapped] += 1.0
        used += 1
    total = sum(counts.values())
    if total <= 0:
        uniform = 1.0 / len(counts)
        return ({root_id: uniform for root_id in counts}, {"method_detail": "empirical_prior_v1", "training_cases": 0})
    return (
        {root_id: counts[root_id] / total for root_id in counts},
        {"method_detail": "empirical_prior_v1", "training_cases": used},
    )


def _multiclass_brier(ledger: Mapping[str, float], oracle_root_id: str) -> float | None:
    if oracle_root_id not in ledger:
        return None
    total = 0.0
    for root_id, p_value in ledger.items():
        y = 1.0 if root_id == oracle_root_id else 0.0
        total += (p_value - y) ** 2
    return total


def _binary_brier(p_value: float | None) -> float | None:
    if p_value is None:
        return None
    return (p_value - 1.0) ** 2


def _log_loss(p_value: float | None) -> float | None:
    if p_value is None:
        return None
    clipped = min(1.0 - 1e-12, max(1e-12, p_value))
    return -math.log(clipped)


def _oracle_target_roots(oracle_root_id: str, ledger: Mapping[str, float]) -> tuple[List[str], str]:
    if oracle_root_id and oracle_root_id in ledger:
        return [oracle_root_id], "single"

    label = (oracle_root_id or "").strip()
    if label in {"H_OTHER", "H_UND", "H_NOA"}:
        targets = [root_id for root_id in ("H_UND", "H_NOA") if root_id in ledger]
        if targets:
            return targets, "open_world_set"

    return [], "none"


def summarize_prediction(
    *,
    case_id: str,
    split: str,
    event_year: int | None,
    stage_packet: Mapping[str, Any],
    method: str,
    ledger: Mapping[str, float],
    oracle_root_id: str,
    run_info: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    winners, best_p = _top_roots(ledger)
    top1_ambiguous = len(winners) > 1
    top_root_id = winners[0] if len(winners) == 1 else ""

    oracle_targets, oracle_mode = _oracle_target_roots(oracle_root_id, ledger)
    oracle_eval_eligible = bool(oracle_targets)
    oracle_target_p = sum(float(ledger.get(root_id, 0.0)) for root_id in oracle_targets) if oracle_targets else None

    top1_set_match = bool(not top1_ambiguous and top_root_id and top_root_id in oracle_targets)
    oracle_in_top_tie = bool(top1_ambiguous and any(root_id in oracle_targets for root_id in winners))

    if oracle_mode == "single":
        brier = _multiclass_brier(ledger, oracle_targets[0])
    elif oracle_mode == "open_world_set":
        brier = _binary_brier(oracle_target_p)
    else:
        brier = None
    log_loss = _log_loss(oracle_target_p)

    row = {
        "case_id": case_id,
        "split": split,
        "event_year": event_year,
        "method": method,
        "stage_id": str(stage_packet.get("stage_id", "")),
        "stage_index": int(stage_packet.get("stage_index", -1)),
        "stage_description": str(stage_packet.get("stage_description", "")),
        "stage_mode": str(stage_packet.get("stage_mode", "")),
        "stage_selection_mode": str(stage_packet.get("stage_selection_mode", "")),
        "base_item_count": int(stage_packet.get("base_item_count", 0)),
        "item_count": int(stage_packet.get("item_count", 0)),
        "oracle_root_id": oracle_root_id,
        "oracle_eval_mode": oracle_mode,
        "oracle_target_roots": oracle_targets,
        "oracle_eval_eligible": oracle_eval_eligible,
        "oracle_target_p": None if oracle_target_p is None else round(float(oracle_target_p), 8),
        "top_root_id": top_root_id,
        "top_root_ids": winners,
        "top_root_p": round(best_p, 8),
        "top1_ambiguous": top1_ambiguous,
        "top1_match": top1_set_match,
        "oracle_in_top_tie": oracle_in_top_tie,
        "brier": None if brier is None else round(float(brier), 8),
        "log_loss": None if log_loss is None else round(float(log_loss), 8),
        "status": "ok",
    }
    if run_info:
        row.update(dict(run_info))
    return row


def _mean(values: Iterable[float | None]) -> float | None:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def aggregate_stage_metrics(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], List[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        key = (str(row.get("method", "")), str(row.get("stage_id", "")))
        grouped.setdefault(key, []).append(row)

    aggregates: List[Dict[str, Any]] = []
    for (method, stage_id), group in sorted(grouped.items()):
        eligible = [row for row in group if bool(row.get("oracle_eval_eligible"))]
        stage_index = min(int(row.get("stage_index", -1)) for row in group)
        top1_hits = sum(1 for row in eligible if bool(row.get("top1_match")))
        tie_hits = sum(
            1 for row in eligible if bool(row.get("top1_match")) or bool(row.get("oracle_in_top_tie"))
        )
        denom = len(eligible)
        mean_top_root_p = _mean(_safe_float(row.get("top_root_p")) for row in group)
        mean_oracle_p = _mean(_safe_float(row.get("oracle_target_p")) for row in eligible)
        mean_brier = _mean(_safe_float(row.get("brier")) for row in eligible)
        mean_log_loss = _mean(_safe_float(row.get("log_loss")) for row in eligible)
        aggregates.append(
            {
                "method": method,
                "stage_id": stage_id,
                "stage_index": stage_index,
                "cases": len(group),
                "eval_eligible_cases": denom,
                "top1_accuracy": None if denom == 0 else round(top1_hits / denom, 8),
                "top1_or_tie_hit_rate": None if denom == 0 else round(tie_hits / denom, 8),
                "ambiguous_rate": round(
                    sum(1 for row in group if bool(row.get("top1_ambiguous"))) / len(group), 8
                ),
                "mean_top_root_p": None if mean_top_root_p is None else round(mean_top_root_p, 8),
                "mean_oracle_target_p": None if mean_oracle_p is None else round(mean_oracle_p, 8),
                "mean_brier": None if mean_brier is None else round(mean_brier, 8),
                "mean_log_loss": None if mean_log_loss is None else round(mean_log_loss, 8),
            }
        )
    return sorted(aggregates, key=lambda row: (str(row.get("method", "")), int(row.get("stage_index", -1))))


def _write_csv(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            serializable = dict(row)
            for key in ("top_root_ids", "oracle_target_roots"):
                value = serializable.get(key)
                if isinstance(value, list):
                    serializable[key] = "|".join(str(item) for item in value)
            writer.writerow(serializable)


def _write_backtest_summary(report: Mapping[str, Any], path: Path) -> None:
    rows = list(report.get("rows", []))
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    err_rows = [row for row in rows if row.get("status") != "ok"]
    aggregates = list(report.get("aggregates", []))
    provenance = dict(report.get("provenance", {}))

    lines = [
        f"# AAIB Historical Backtest Summary ({report.get('report_id', '')})",
        "",
        "## Provenance",
        f"- created_at_utc: `{report.get('created_at_utc', '')}`",
        f"- aaib_bench_version: `{provenance.get('aaib_bench_version', '')}`",
        f"- repo_git_sha: `{provenance.get('repo_git_sha', '')}`",
        f"- repo_git_ref: `{provenance.get('repo_git_ref', '')}`",
        "",
        "## Settings",
        f"- mode: `{report.get('mode', '')}`",
        f"- methods: `{','.join(str(m) for m in report.get('methods', []))}`",
        f"- holdout_year: `{report.get('holdout_year', '')}`",
        f"- run_dev: `{report.get('run_dev', '')}`",
        f"- selected_only: `{report.get('selected_only', '')}`",
        f"- credits: `{report.get('credits', '')}`",
        f"- model: `{report.get('model', '')}`",
        f"- temperature: `{report.get('temperature', '')}`",
        f"- timeout_s: `{report.get('timeout_s', '')}`",
        f"- strict_mece: `{report.get('strict_mece', '')}`",
        f"- max_pair_overlap: `{report.get('max_pair_overlap', '')}`",
        f"- hardened_one_shot: `{report.get('hardened_one_shot', '')}`",
        f"- locked_policy_profile: `{report.get('locked_policy_profile', '')}`",
        "",
        "## Aggregate Results",
        f"- total_rows: `{len(rows)}`",
        f"- ok_rows: `{len(ok_rows)}`",
        f"- error_rows: `{len(err_rows)}`",
        "",
        "## Stage Aggregates",
        "| method | stage_id | cases | top1_accuracy | top1_or_tie_hit_rate | mean_oracle_target_p | mean_brier | mean_log_loss |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for aggregate in aggregates:
        lines.append(
            "| {method} | {stage_id} | {cases} | {top1_accuracy} | {top1_or_tie_hit_rate} | {mean_oracle_target_p} | {mean_brier} | {mean_log_loss} |".format(
                method=str(aggregate.get("method", "abductio")),
                stage_id=str(aggregate.get("stage_id", "")),
                cases=str(aggregate.get("cases", "")),
                top1_accuracy=str(aggregate.get("top1_accuracy", "")),
                top1_or_tie_hit_rate=str(aggregate.get("top1_or_tie_hit_rate", "")),
                mean_oracle_target_p=str(aggregate.get("mean_oracle_target_p", "")),
                mean_brier=str(aggregate.get("mean_brier", "")),
                mean_log_loss=str(aggregate.get("mean_log_loss", "")),
            )
        )

    lines.extend(
        [
            "",
            "## Row Outcomes",
            "| case_id | method | stage_id | status | top_root_id | oracle_root_id | top1_match | oracle_target_p | top_root_p | stop_reason |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {case_id} | {method} | {stage_id} | {status} | {top_root_id} | {oracle_root_id} | {top1_match} | {oracle_target_p} | {top_root_p} | {stop_reason} |".format(
                case_id=str(row.get("case_id", "")),
                method=str(row.get("method", "abductio")),
                stage_id=str(row.get("stage_id", "")),
                status=str(row.get("status", "")),
                top_root_id=str(row.get("top_root_id", "")),
                oracle_root_id=str(row.get("oracle_root_id", "")),
                top1_match=str(row.get("top1_match", "")),
                oracle_target_p=str(row.get("oracle_target_p", "")),
                top_root_p=str(row.get("top_root_p", "")),
                stop_reason=str(row.get("stop_reason", "")),
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _select_rows(
    *,
    case_ids: Sequence[str],
    holdout_year: int | None,
    selected_only: bool,
) -> tuple[List[Dict[str, str]], int | None]:
    registry = Registry.load(corpus_root() / "index.csv")
    index = {row.get("case_id", ""): row for row in registry.rows}
    rows: List[Dict[str, str]] = []
    for case_id in case_ids:
        row = index.get(case_id)
        if not row:
            continue
        if selected_only and str(row.get("selected_for_corpus", "")).strip().upper() != "Y":
            continue
        rows.append(dict(row))

    if holdout_year is not None:
        return rows, holdout_year

    years = sorted(
        {
            year
            for year in (_parse_year(str(row.get("date_utc", ""))) for row in rows)
            if year is not None
        }
    )
    return rows, (years[-1] if years else None)


def _split_for_row(row: Mapping[str, str], holdout_year: int | None) -> str:
    if holdout_year is None:
        return "unknown"
    year = _parse_year(str(row.get("date_utc", "")))
    if year == holdout_year:
        return "holdout"
    return "dev"


def _extract_ledger_from_result(run_dir: Path) -> Dict[str, float]:
    result_path = run_dir / "result.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))
    raw_ledger = data.get("ledger", {})
    ledger: Dict[str, float] = {}
    if isinstance(raw_ledger, dict):
        for root_id, value in raw_ledger.items():
            score = _safe_float(value)
            if score is None:
                continue
            ledger[str(root_id)] = float(score)
    return ledger


def run_historical_backtest(
    *,
    case_ids: Sequence[str],
    holdout_year: int | None = None,
    run_dev: bool = False,
    selected_only: bool = True,
    credits: int = 10,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    strict_mece: bool | None = None,
    max_pair_overlap: float | None = None,
    hardened_one_shot: bool = False,
    locked_policy_profile: str | None = None,
    locked_policy_required_case_ids: Sequence[str] | None = None,
    methods: Sequence[str] | None = None,
    abductio_policy_override: Mapping[str, Any] | None = None,
    ablation_label: str | None = None,
) -> Path:
    resolved_methods = _parse_methods(methods)
    resolved_locked_profile_id, resolved_locked_profile_policy = _resolve_locked_policy_profile(locked_policy_profile)
    required_locked_case_ids = (
        set(str(case_id).strip() for case_id in locked_policy_required_case_ids)
        if locked_policy_required_case_ids is not None
        else set(LOCKED_POLICY_REQUIRED_CASE_IDS)
    )
    selected_rows, resolved_holdout_year = _select_rows(
        case_ids=case_ids,
        holdout_year=holdout_year,
        selected_only=selected_only,
    )
    leakage_keywords = _load_leakage_keywords()

    rows: List[Dict[str, Any]] = []
    for row in selected_rows:
        case_id = str(row.get("case_id", ""))
        event_year = _parse_year(str(row.get("date_utc", "")))
        split = _split_for_row(row, resolved_holdout_year)
        if split == "dev" and not run_dev:
            continue

        case_dir = corpus_root() / "cases" / case_id
        evidence_path = case_dir / "evidence_packet.json"
        if not evidence_path.exists():
            rows.append(
                {
                    "case_id": case_id,
                    "method": "-",
                    "split": split,
                    "event_year": event_year,
                    "status": "error",
                    "error": f"Missing evidence_packet.json: {evidence_path}",
                }
            )
            continue

        evidence_packet = json.loads(evidence_path.read_text(encoding="utf-8"))
        stage_packets = load_case_stage_packets(case_dir, evidence_packet)
        oracle_root_id = _read_answer_root(case_dir) or str(row.get("label_root_id", "")).strip()

        try:
            root_context = _load_root_context(case_dir)
        except Exception as exc:
            rows.append(
                {
                    "case_id": case_id,
                    "method": "-",
                    "split": split,
                    "event_year": event_year,
                    "status": "error",
                    "error": f"Root context load failed: {exc}",
                }
            )
            continue

        training_rows = [
            candidate
            for candidate in selected_rows
            if str(candidate.get("case_id", "")) != case_id and _split_for_row(candidate, resolved_holdout_year) != "holdout"
        ]

        for stage_packet in stage_packets:
            stage_id = str(stage_packet.get("stage_id", ""))
            stage_items = list(stage_packet.get("items", []))
            hits = _leakage_hits(stage_items, leakage_keywords)
            if hits:
                rows.append(
                    {
                        "case_id": case_id,
                        "method": "-",
                        "split": split,
                        "event_year": event_year,
                        "stage_id": stage_id,
                        "stage_index": int(stage_packet.get("stage_index", -1)),
                        "status": "error",
                        "error": f"Leakage keywords in stage packet: {', '.join(hits)}",
                    }
                )
                continue

            for method in resolved_methods:
                try:
                    if method == "abductio":
                        if case_id in required_locked_case_ids and not resolved_locked_profile_id:
                            raise ValueError(
                                f"Locked policy profile required for case {case_id}. "
                                "Use locked_policy_profile='boeing_inference_v1'."
                            )
                        run_tag = f"hist_{stage_id.lower()}"
                        if ablation_label:
                            run_tag = f"hist_{str(ablation_label).strip().lower()}_{stage_id.lower()}"
                        effective_policy_override: Dict[str, Any] = {}
                        if resolved_locked_profile_policy is not None:
                            effective_policy_override.update(dict(resolved_locked_profile_policy))
                        if abductio_policy_override is not None:
                            effective_policy_override.update(dict(abductio_policy_override))
                        run_kwargs: Dict[str, Any] = {
                            "case_id": case_id,
                            "credits": credits,
                            "model": model,
                            "temperature": temperature,
                            "timeout_s": timeout_s,
                            "strict_mece": strict_mece,
                            "max_pair_overlap": max_pair_overlap,
                            "hardened_one_shot": bool(hardened_one_shot),
                            "evidence_items_override": stage_items,
                            "run_tag": run_tag,
                            "extra_meta": {
                                "benchmark_mode": "staged_historical_proxy_v2",
                                "split": split,
                                "holdout_year": resolved_holdout_year,
                                "stage_id": stage_id,
                                "method": method,
                                "ablation_label": ablation_label or "",
                            },
                        }
                        if effective_policy_override:
                            run_kwargs["policy_override"] = effective_policy_override
                        if resolved_locked_profile_id:
                            run_kwargs["policy_profile_id"] = resolved_locked_profile_id
                            run_kwargs["enforce_policy_preflight"] = True
                        run_dir = run_case(
                            **run_kwargs,
                        )
                        ledger = _extract_ledger_from_result(run_dir)
                        result_data = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
                        run_info = {
                            "run_dir": str(run_dir),
                            "stop_reason": result_data.get("stop_reason"),
                            "total_credits_spent": result_data.get("total_credits_spent"),
                            "ablation_label": ablation_label or "",
                        }
                    elif method == "logodds":
                        ledger, baseline_meta = _baseline_logodds(stage_items, root_context)
                        run_info = baseline_meta
                    elif method == "checklist":
                        ledger, baseline_meta = _baseline_checklist(stage_items, root_context)
                        run_info = baseline_meta
                    elif method == "prior":
                        ledger, baseline_meta = _baseline_prior(training_rows=training_rows, context=root_context)
                        run_info = baseline_meta
                    else:
                        raise ValueError(f"Unsupported method: {method}")

                    rows.append(
                        summarize_prediction(
                            case_id=case_id,
                            split=split,
                            event_year=event_year,
                            stage_packet=stage_packet,
                            method=method,
                            ledger=ledger,
                            oracle_root_id=oracle_root_id,
                            run_info=run_info,
                        )
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "case_id": case_id,
                            "method": method,
                            "split": split,
                            "event_year": event_year,
                            "stage_id": stage_id,
                            "stage_index": int(stage_packet.get("stage_index", -1)),
                            "status": "error",
                            "error": str(exc),
                        }
                    )

    aggregates = aggregate_stage_metrics(rows)
    report_id = _now_stamp()
    report = {
        "report_id": report_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "staged_historical_proxy_v2",
        "methods": resolved_methods,
        "holdout_year": resolved_holdout_year,
        "run_dev": run_dev,
        "selected_only": selected_only,
        "credits": credits,
        "model": model,
        "temperature": temperature,
        "timeout_s": timeout_s,
        "strict_mece": strict_mece,
        "max_pair_overlap": max_pair_overlap,
        "hardened_one_shot": bool(hardened_one_shot),
        "locked_policy_profile": resolved_locked_profile_id or "",
        "ablation_label": ablation_label or "",
        "stage_specs": [
            {
                "stage_id": stage.stage_id,
                "description": stage.description,
                "history_fraction": stage.history_fraction,
                "fallback_fraction": stage.fallback_fraction,
            }
            for stage in DEFAULT_STAGE_SPECS
        ],
        "rows": rows,
        "aggregates": aggregates,
        "provenance": collect_provenance(),
    }

    out_dir = _results_dir()
    json_path = out_dir / f"{report_id}.json"
    csv_path = out_dir / f"{report_id}.csv"
    markdown_path = out_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(rows, csv_path)
    _write_backtest_summary(report, markdown_path)
    return json_path


def _ablation_variant_policies() -> List[Dict[str, Any]]:
    baseline_policy: Dict[str, Any] = {
        "reasoning_profile": "causal_investigation",
        "reasoning_mode": "certify",
        "contender_space_mode": "singleton_roots",
        "strict_contrastive_updates_required": True,
        "decision_contract_enabled": True,
        "decision_min_pairwise_coverage_ratio": 1.0,
        "decision_min_winner_margin": 0.15,
        "decision_active_set_enabled": True,
        "decision_active_set_size": 3,
        "decision_active_set_mass_ratio": 0.60,
        "closure_active_set_adjudication_required": True,
        "closure_active_set_size": 3,
        "closure_active_set_mass_ratio": 0.60,
        "closure_min_pairwise_coverage_ratio": 1.0,
        "decision_require_loser_falsification": True,
        "decision_require_counterevidence_probe": True,
        "typed_discriminator_evidence_required": True,
        "evidence_discrimination_tags_required": True,
        "pair_resolution_engine_enabled": True,
        "pair_resolution_min_directional_margin": 0.15,
        "pair_resolution_min_directional_evidence_count": 1,
        "pair_resolution_max_contradiction_density": 0.45,
        "pair_resolution_winner_update_gain": 0.20,
        "strict_non_discriminative_margin_epsilon": 0.0,
        "coverage_confidence_cap_enabled": True,
        "coverage_confidence_cap_base": 0.40,
        "coverage_confidence_cap_gain": 0.50,
        "contrastive_budget_partition_enabled": True,
        "min_contrastive_discriminator_credits": 2,
        "min_counterevidence_credits": 1,
        "pair_adjudication_queue_enabled": False,
        "dynamic_abstention_mass_enabled": False,
        "compositional_story_auto_expand": False,
        "contender_story_max_cardinality": 2,
    }

    pair_engine = dict(baseline_policy)
    pair_engine.update(
        {
            "pair_adjudication_queue_enabled": True,
            "pair_adjudication_scope": "active_set",
            "pair_adjudication_active_set_size": 3,
            "pair_adjudication_active_set_mass_ratio": 0.60,
        }
    )

    dynamic_und = dict(pair_engine)
    dynamic_und.update(
        {
            "dynamic_abstention_mass_enabled": True,
            "dynamic_abstention_unresolved_pair_weight": 0.30,
            "dynamic_abstention_contradiction_density_weight": 0.25,
            "dynamic_abstention_non_discriminative_weight": 0.20,
            "dynamic_abstention_mass_minimum": 0.05,
            "dynamic_abstention_mass_maximum": 0.90,
        }
    )

    composition = dict(dynamic_und)
    composition.update(
        {
            "contender_space_mode": "compositional_stories",
            "compositional_story_auto_expand": True,
            "contender_story_max_cardinality": 2,
        }
    )

    return [
        {
            "variant_id": "baseline",
            "description": "Baseline without pair adjudication queue or dynamic abstention.",
            "policy_override": baseline_policy,
        },
        {
            "variant_id": "pair_engine",
            "description": "Baseline + unresolved-pair adjudication queue.",
            "policy_override": pair_engine,
        },
        {
            "variant_id": "dynamic_und",
            "description": "Pair engine + dynamic abstention mass.",
            "policy_override": dynamic_und,
        },
        {
            "variant_id": "composition",
            "description": "Dynamic abstention + compositional contender expansion (k<=2).",
            "policy_override": composition,
        },
    ]


def _overall_ablation_metrics(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    total_rows = len(rows)
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    eligible = [row for row in ok_rows if bool(row.get("oracle_eval_eligible"))]
    denom = len(eligible)
    top1_hits = sum(1 for row in eligible if bool(row.get("top1_match")))
    mean_brier = _mean(_safe_float(row.get("brier")) for row in eligible)
    mean_log_loss = _mean(_safe_float(row.get("log_loss")) for row in eligible)

    abstained = [
        row
        for row in eligible
        if bool(row.get("top1_ambiguous")) or str(row.get("top_root_id", "")).strip() in {"H_UND", "H_NOA"}
    ]
    abstain_count = len(abstained)
    abstention_rate = (abstain_count / denom) if denom else None
    honest_abstentions = sum(1 for row in abstained if not bool(row.get("top1_match")))
    abstention_honesty_rate = (honest_abstentions / abstain_count) if abstain_count else None

    return {
        "rows_total": total_rows,
        "rows_ok": len(ok_rows),
        "rows_error": max(0, total_rows - len(ok_rows)),
        "rows_eval_eligible": denom,
        "top1_accuracy": None if denom == 0 else round(top1_hits / denom, 8),
        "mean_brier": None if mean_brier is None else round(float(mean_brier), 8),
        "mean_log_loss": None if mean_log_loss is None else round(float(mean_log_loss), 8),
        "abstention_rate": None if abstention_rate is None else round(float(abstention_rate), 8),
        "abstention_honesty_rate": None
        if abstention_honesty_rate is None
        else round(float(abstention_honesty_rate), 8),
    }


def _write_ablation_summary(report: Mapping[str, Any], path: Path) -> None:
    variants = list(report.get("variants", []))
    lines = [
        f"# AAIB Historical Ablation Summary ({report.get('report_id', '')})",
        "",
        "## Settings",
        f"- created_at_utc: `{report.get('created_at_utc', '')}`",
        f"- holdout_year: `{report.get('holdout_year', '')}`",
        f"- run_dev: `{report.get('run_dev', '')}`",
        f"- selected_only: `{report.get('selected_only', '')}`",
        f"- credits: `{report.get('credits', '')}`",
        f"- model: `{report.get('model', '')}`",
        f"- temperature: `{report.get('temperature', '')}`",
        f"- timeout_s: `{report.get('timeout_s', '')}`",
        f"- strict_mece: `{report.get('strict_mece', '')}`",
        f"- max_pair_overlap: `{report.get('max_pair_overlap', '')}`",
        f"- locked_policy_profile: `{report.get('locked_policy_profile', '')}`",
        "",
        "## Variant Metrics",
        "| variant | rows_ok | rows_error | rows_eval_eligible | top1_accuracy | mean_brier | mean_log_loss | abstention_rate | abstention_honesty_rate | delta_top1_accuracy | delta_mean_brier |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in variants:
        metrics = dict(row.get("metrics", {}))
        lines.append(
            "| {variant_id} | {rows_ok} | {rows_error} | {rows_eval_eligible} | {top1_accuracy} | {mean_brier} | {mean_log_loss} | {abstention_rate} | {abstention_honesty_rate} | {delta_top1_accuracy} | {delta_mean_brier} |".format(
                variant_id=str(row.get("variant_id", "")),
                rows_ok=str(metrics.get("rows_ok", "")),
                rows_error=str(metrics.get("rows_error", "")),
                rows_eval_eligible=str(metrics.get("rows_eval_eligible", "")),
                top1_accuracy=str(metrics.get("top1_accuracy", "")),
                mean_brier=str(metrics.get("mean_brier", "")),
                mean_log_loss=str(metrics.get("mean_log_loss", "")),
                abstention_rate=str(metrics.get("abstention_rate", "")),
                abstention_honesty_rate=str(metrics.get("abstention_honesty_rate", "")),
                delta_top1_accuracy=str(row.get("delta_top1_accuracy", "")),
                delta_mean_brier=str(row.get("delta_mean_brier", "")),
            )
        )

    lines.extend(["", "## Variant Reports", "| variant | report_json |", "| --- | --- |"])
    for row in variants:
        lines.append(
            "| {variant_id} | {report_json} |".format(
                variant_id=str(row.get("variant_id", "")),
                report_json=str(row.get("report_json", "")),
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_historical_ablation_suite(
    *,
    case_ids: Sequence[str],
    holdout_year: int | None = None,
    run_dev: bool = False,
    selected_only: bool = True,
    credits: int = 10,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    strict_mece: bool | None = None,
    max_pair_overlap: float | None = None,
    locked_policy_profile: str | None = None,
) -> Path:
    variants = _ablation_variant_policies()
    variant_rows: List[Dict[str, Any]] = []
    baseline_metrics: Dict[str, Any] | None = None

    for variant in variants:
        variant_id = str(variant.get("variant_id", "")).strip()
        policy_override = dict(variant.get("policy_override", {}))
        report_json = run_historical_backtest(
            case_ids=case_ids,
            holdout_year=holdout_year,
            run_dev=run_dev,
            selected_only=selected_only,
            credits=credits,
            model=model,
            temperature=temperature,
            timeout_s=timeout_s,
            strict_mece=strict_mece,
            max_pair_overlap=max_pair_overlap,
            hardened_one_shot=False,
            methods=["abductio"],
            locked_policy_profile=locked_policy_profile,
            abductio_policy_override=policy_override,
            ablation_label=variant_id,
        )
        report_data = json.loads(report_json.read_text(encoding="utf-8"))
        metrics = _overall_ablation_metrics(report_data.get("rows", []))

        entry: Dict[str, Any] = {
            "variant_id": variant_id,
            "description": str(variant.get("description", "")),
            "policy_override": policy_override,
            "report_json": str(report_json),
            "report_markdown": str(report_json.with_suffix(".md")),
            "metrics": metrics,
        }
        if baseline_metrics is None:
            baseline_metrics = metrics
            entry["delta_top1_accuracy"] = 0.0
            entry["delta_mean_brier"] = 0.0
        else:
            baseline_top1 = _safe_float(baseline_metrics.get("top1_accuracy"))
            current_top1 = _safe_float(metrics.get("top1_accuracy"))
            baseline_brier = _safe_float(baseline_metrics.get("mean_brier"))
            current_brier = _safe_float(metrics.get("mean_brier"))
            entry["delta_top1_accuracy"] = (
                None
                if baseline_top1 is None or current_top1 is None
                else round(current_top1 - baseline_top1, 8)
            )
            entry["delta_mean_brier"] = (
                None
                if baseline_brier is None or current_brier is None
                else round(current_brier - baseline_brier, 8)
            )
        variant_rows.append(entry)

    report_id = f"{_now_stamp()}_ablation"
    report = {
        "report_id": report_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "staged_historical_ablation_v1",
        "holdout_year": holdout_year,
        "run_dev": run_dev,
        "selected_only": selected_only,
        "credits": credits,
        "model": model,
        "temperature": temperature,
        "timeout_s": timeout_s,
        "strict_mece": strict_mece,
        "max_pair_overlap": max_pair_overlap,
        "locked_policy_profile": str(locked_policy_profile or ""),
        "variants": variant_rows,
        "provenance": collect_provenance(),
    }

    out_dir = _results_dir()
    json_path = out_dir / f"{report_id}.json"
    markdown_path = out_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_ablation_summary(report, markdown_path)
    return json_path
