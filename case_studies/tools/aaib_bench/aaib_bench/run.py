from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.adapters.openai_llm import OpenAIDecomposerPort, OpenAIEvaluatorPort, OpenAIJsonClient
from abductio_core.application.dto import EvidenceItem
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent

from .config import corpus_root, spec_root


@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        cleaned = value.strip().strip("\"'").strip()
        values[key] = cleaned
    return values


def _load_local_env_defaults() -> None:
    # Make local CLI runs less fragile by loading project .env values when present.
    env_path = Path.cwd() / ".env"
    values = _parse_env_file(env_path)
    for key, value in values.items():
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_csv(name: str) -> Tuple[str, ...]:
    raw = os.getenv(name, "")
    if not raw:
        return ()
    parts = [part.strip() for part in raw.split(",")]
    return tuple(part for part in parts if part)


def _load_roots(case_dir: Path) -> Tuple[str, List[RootSpec], Dict[str, str], Dict[str, Any]]:
    roots_yaml = case_dir.joinpath("roots.yaml").read_text(encoding="utf-8").splitlines()
    root_set_id = ""
    root_ids: List[str] = []
    for line in roots_yaml:
        line = line.strip()
        if line.startswith("root_set_id:"):
            root_set_id = line.split(":", 1)[1].strip()
        if line.startswith("- id:"):
            root_ids.append(line.split(":", 1)[1].strip())

    library = json.loads(spec_root().joinpath("roots_library.json").read_text(encoding="utf-8"))
    root_sets = library.get("root_sets", {})
    if not root_set_id:
        raise ValueError(f"roots.yaml missing root_set_id for case {case_dir.name}")
    root_set = root_sets.get(root_set_id)
    if not isinstance(root_set, dict):
        raise ValueError(f"root_set_id {root_set_id!r} not found in roots_library.json")
    label_map: Dict[str, str] = {}
    for raw_root in root_set.get("roots", []):
        if not isinstance(raw_root, dict):
            continue
        root_key = str(raw_root.get("id", "")).strip()
        if not root_key:
            continue
        base_label = str(raw_root.get("label", root_key)).strip() or root_key
        nec_slots = raw_root.get("nec_slots", [])
        nec_descriptions: List[str] = []
        if isinstance(nec_slots, list):
            for slot in nec_slots:
                if not isinstance(slot, dict):
                    continue
                desc = str(slot.get("description", "")).strip()
                if desc:
                    nec_descriptions.append(desc)
        if nec_descriptions:
            statement = f"{base_label}. NEC: {'; '.join(nec_descriptions)}"
        else:
            statement = base_label
        label_map[root_key] = statement

    roots: List[RootSpec] = []
    for root_id in root_ids:
        if root_id == "H_OTHER":
            continue
        statement = label_map.get(root_id, root_id)
        roots.append(
            RootSpec(
                root_id=root_id,
                statement=statement,
                exclusion_clause="Not explained by any other root",
            )
        )
    root_statements = {root.root_id: root.statement for root in roots}
    return root_set_id, roots, root_statements, root_set


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected numeric value, got {value!r}") from exc


def _resolve_mece_controls(
    *,
    root_set: Mapping[str, Any],
    strict_mece: bool | None,
    max_pair_overlap: float | None,
    mece_certificate_override: Mapping[str, Any] | None,
) -> tuple[Dict[str, Any] | None, bool | None, float | None]:
    configured_certificate = root_set.get("mece_certificate")
    if configured_certificate is not None and not isinstance(configured_certificate, dict):
        raise ValueError("roots_library root_set.mece_certificate must be an object when provided")
    mece_certificate = dict(configured_certificate) if isinstance(configured_certificate, dict) else None
    if mece_certificate_override is not None:
        mece_certificate = dict(mece_certificate_override)

    strict_default = root_set.get("strict_mece_default")
    strict_resolved = strict_mece
    if strict_resolved is None and isinstance(strict_default, bool):
        strict_resolved = strict_default
    if strict_resolved is None and isinstance(mece_certificate, dict):
        strict_resolved = bool(mece_certificate.get("strict", False))

    overlap_resolved = max_pair_overlap
    if overlap_resolved is None:
        overlap_resolved = _coerce_optional_float(root_set.get("max_pair_overlap"))
    if overlap_resolved is None and isinstance(mece_certificate, dict):
        overlap_resolved = _coerce_optional_float(mece_certificate.get("max_pair_overlap"))

    return mece_certificate, strict_resolved, overlap_resolved


def _policy_fingerprint(policy: Mapping[str, Any] | None) -> str:
    payload = dict(policy or {})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_policy_preflight(*, policy_profile_id: str, policy_payload: Mapping[str, Any] | None) -> None:
    profile = str(policy_profile_id).strip()
    if not profile:
        raise ValueError("Policy preflight failed: non-empty policy_profile_id is required.")
    if not isinstance(policy_payload, Mapping) or not dict(policy_payload):
        raise ValueError("Policy preflight failed: non-empty policy override is required.")
    if not bool(policy_payload.get("pair_resolution_engine_enabled")):
        raise ValueError("Policy preflight failed: pair_resolution_engine_enabled must be true.")


def hardened_one_shot_policy_defaults() -> Dict[str, Any]:
    return {
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
        "pair_adjudication_queue_enabled": True,
        "pair_adjudication_scope": "active_set",
        "pair_adjudication_active_set_size": 3,
        "pair_adjudication_active_set_mass_ratio": 0.60,
        "dynamic_abstention_mass_enabled": True,
        "dynamic_abstention_unresolved_pair_weight": 0.30,
        "dynamic_abstention_contradiction_density_weight": 0.25,
        "dynamic_abstention_non_discriminative_weight": 0.20,
        "dynamic_abstention_mass_minimum": 0.05,
        "dynamic_abstention_mass_maximum": 0.90,
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
    }


def run_case(
    case_id: str,
    credits: int = 10,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    strict_mece: bool | None = None,
    max_pair_overlap: float | None = None,
    mece_certificate_override: Mapping[str, Any] | None = None,
    policy_override: Mapping[str, Any] | None = None,
    policy_profile_id: str | None = None,
    enforce_policy_preflight: bool = False,
    hardened_one_shot: bool = False,
    evidence_items_override: List[Dict[str, Any]] | None = None,
    run_tag: str | None = None,
    extra_meta: Mapping[str, Any] | None = None,
) -> Path:
    _load_local_env_defaults()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set to run ABDUCTIO with OpenAI adapters.")

    case_dir = corpus_root() / "cases" / case_id
    evidence_path = case_dir / "evidence_packet.json"
    if not evidence_path.exists():
        raise FileNotFoundError(f"Missing evidence_packet.json for {case_id}")
    evidence_packet = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_items = list(evidence_items_override) if evidence_items_override is not None else evidence_packet.get("items", [])

    scope = case_id if not run_tag else f"{case_id}:{run_tag}"

    root_set_id, roots, root_statements, root_set = _load_roots(case_dir)
    mece_certificate, strict_mece_resolved, max_pair_overlap_resolved = _resolve_mece_controls(
        root_set=root_set,
        strict_mece=strict_mece,
        max_pair_overlap=max_pair_overlap,
        mece_certificate_override=mece_certificate_override,
    )
    policy: Dict[str, Any] = {}
    configured_policy = root_set.get("policy")
    if isinstance(configured_policy, dict):
        policy.update(configured_policy)
    if hardened_one_shot:
        policy.update(hardened_one_shot_policy_defaults())
    if policy_override is not None:
        policy.update(dict(policy_override))
    policy_payload = policy or None
    resolved_policy_profile_id = str(policy_profile_id or "").strip()
    if not resolved_policy_profile_id and hardened_one_shot:
        resolved_policy_profile_id = "safe_baseline_v2"
    if enforce_policy_preflight:
        _validate_policy_preflight(
            policy_profile_id=resolved_policy_profile_id,
            policy_payload=policy_payload,
        )
    policy_fingerprint = _policy_fingerprint(policy_payload)

    client = OpenAIJsonClient(
        model=model,
        temperature=temperature,
        timeout_s=timeout_s,
        max_retries=_env_int("ABDUCTIO_OPENAI_MAX_RETRIES", 6),
        retry_backoff_s=_env_float("ABDUCTIO_OPENAI_RETRY_BACKOFF_S", 1.0),
        retry_backoff_max_s=_env_float("ABDUCTIO_OPENAI_RETRY_BACKOFF_MAX_S", 15.0),
        retry_jitter_s=_env_float("ABDUCTIO_OPENAI_RETRY_JITTER_S", 0.25),
        fallback_models=_env_csv("ABDUCTIO_OPENAI_FALLBACK_MODELS"),
        base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE"),
    )
    evaluator = OpenAIEvaluatorPort(
        client=client,
        scope=scope,
        root_statements=root_statements,
        evidence_items=[
            {"id": item.get("id", ""), "source": item.get("source", ""), "text": item.get("text", "")}
            for item in evidence_items
        ],
    )
    decomposer = OpenAIDecomposerPort(
        client=client,
        required_slots_hint=["availability", "fit_to_key_features", "defeater_resistance"],
        scope=scope,
        root_statements=root_statements,
    )

    class NoopSearcher:
        def search(self, query: str, *, limit: int, metadata: Dict[str, Any]) -> List[EvidenceItem]:
            return []

    audit = MemAudit()
    deps = RunSessionDeps(
        evaluator=evaluator,
        decomposer=decomposer,
        audit_sink=audit,
        searcher=NoopSearcher(),
    )

    request = SessionRequest(
        scope=scope,
        roots=roots,
        config=SessionConfig(
            tau=0.70,
            epsilon=0.05,
            gamma_noa=0.10,
            gamma_und=0.10,
            gamma=0.20,
            alpha=0.40,
            beta=1.0,
            W=3.0,
            lambda_voi=0.10,
            world_mode="open",
        ),
        credits=credits,
        required_slots=[
            {"slot_key": "availability", "role": "NEC"},
            {"slot_key": "fit_to_key_features", "role": "NEC"},
            {"slot_key": "defeater_resistance", "role": "NEC"},
        ],
        mece_certificate=mece_certificate,
        strict_mece=strict_mece_resolved,
        max_pair_overlap=max_pair_overlap_resolved,
        evidence_items=evidence_items,
        policy=policy_payload,
    )

    result = run_session(request, deps)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if run_tag:
        safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", run_tag).strip("._-")
        if safe_tag:
            run_id = f"{run_id}--{safe_tag}"
    run_dir = case_dir / "runs" / "abductio" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "case_id": case_id,
        "run_id": run_id,
        "scope": scope,
        "root_set_id": root_set_id,
        "run_tag": run_tag or "",
        "model": model,
        "temperature": temperature,
        "timeout_s": timeout_s,
        "credits": credits,
        "strict_mece": strict_mece_resolved,
        "max_pair_overlap": max_pair_overlap_resolved,
        "mece_certificate_present": bool(mece_certificate),
        "mece_certificate_pairwise_overlap_count": len((mece_certificate or {}).get("pairwise_overlaps", {}))
        if isinstance(mece_certificate, dict)
        else 0,
        "mece_certificate_pairwise_discriminator_count": len((mece_certificate or {}).get("pairwise_discriminators", {}))
        if isinstance(mece_certificate, dict)
        else 0,
        "hardened_one_shot": bool(hardened_one_shot),
        "policy_profile_id": resolved_policy_profile_id,
        "policy_fingerprint": policy_fingerprint,
        "policy": dict(policy_payload or {}),
        "evidence_items_count": len(evidence_items),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "openai_max_retries": client.max_retries,
        "openai_retry_backoff_s": client.retry_backoff_s,
        "openai_retry_backoff_max_s": client.retry_backoff_max_s,
        "openai_retry_jitter_s": client.retry_jitter_s,
        "openai_fallback_models": list(client.fallback_models),
        "openai_base_url": client.base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "",
    }
    if extra_meta:
        run_meta["extra_meta"] = dict(extra_meta)

    run_dir.joinpath("run_meta.json").write_text(
        json.dumps(run_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("request.json").write_text(
        json.dumps(asdict(request), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("result.json").write_text(
        json.dumps(result.to_dict_view(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("audit_trace.json").write_text(
        json.dumps(
            [{"event_type": event.event_type, "payload": event.payload} for event in audit.events],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return run_dir
