from __future__ import annotations

from typing import Any, Dict, List, Optional

from abductio_core.application.dto import EvidenceItem, RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.result import SessionResult
from abductio_core.domain.audit import AuditEvent
from abductio_core.domain.invariants import H_UND_ID
from abductio_core.application.use_cases.run_session import run_session


SIMPLE_PROFILE = "simple_v1"
SIMPLE_ROOT_YES_ID = "H_YES"
SIMPLE_ROOT_NO_ID = "H_NO"

DEFAULT_SIMPLE_CONFIG = SessionConfig(
    tau=0.75,
    epsilon=0.05,
    gamma_noa=0.10,
    gamma_und=0.10,
    alpha=1.00,
    beta=1.00,
    W=3.00,
    lambda_voi=0.10,
    world_mode="open",
    rho_eval_min=0.50,
    gamma=0.0,
)

DEFAULT_SIMPLE_REQUIRED_SLOTS: List[Dict[str, Any]] = [
    {"slot_key": "availability", "role": "NEC"},
    {"slot_key": "fit_to_key_features", "role": "NEC"},
    {"slot_key": "defeater_resistance", "role": "NEC"},
]


def _clean_claim(claim: str) -> str:
    return " ".join(str(claim or "").split()).strip()


def _build_simple_roots(claim: str) -> List[RootSpec]:
    clean = _clean_claim(claim)
    return [
        RootSpec(
            root_id=SIMPLE_ROOT_YES_ID,
            statement=clean,
            exclusion_clause="Not explained by H_NO; unresolved uncertainty belongs in H_UND.",
        ),
        RootSpec(
            root_id=SIMPLE_ROOT_NO_ID,
            statement=f"It is not the case that: {clean}",
            exclusion_clause="Not explained by H_YES; unresolved uncertainty belongs in H_UND.",
        ),
    ]


def build_simple_claim_request(
    claim: str,
    *,
    credits: Optional[int] = None,
    config: Optional[SessionConfig] = None,
    required_slots: Optional[List[Dict[str, Any]]] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
    framing: Optional[str] = None,
    run_mode: str = "until_stops",
    policy: Optional[Dict[str, Any]] = None,
) -> SessionRequest:
    clean = _clean_claim(claim)
    if not clean:
        raise ValueError("claim must be non-empty")
    selected_config = config or DEFAULT_SIMPLE_CONFIG
    selected_slots = required_slots or list(DEFAULT_SIMPLE_REQUIRED_SLOTS)
    selected_credits = int(credits) if credits is not None else 12
    if selected_credits < 0:
        raise ValueError("credits must be non-negative")
    roots = _build_simple_roots(clean)
    return SessionRequest(
        scope=f"Simple claim evaluation: {clean}",
        roots=roots,
        config=selected_config,
        credits=selected_credits,
        required_slots=selected_slots,
        run_mode=run_mode,
        evidence_items=evidence_items,
        pre_scoped_roots=[SIMPLE_ROOT_YES_ID, SIMPLE_ROOT_NO_ID],
        strict_mece=False,
        mece_certificate=None,
        max_pair_overlap=None,
        framing=framing,
        policy=dict(policy) if isinstance(policy, dict) else None,
    )


def _derive_simple_opinion(result: SessionResult, tie_epsilon: float) -> Dict[str, Any]:
    ledger = result.ledger
    yes_p = float(ledger.get(SIMPLE_ROOT_YES_ID, 0.0))
    no_p = float(ledger.get(SIMPLE_ROOT_NO_ID, 0.0))
    und_p = float(ledger.get(H_UND_ID, 0.0))

    ranked = sorted(
        [(yes_p, SIMPLE_ROOT_YES_ID), (no_p, SIMPLE_ROOT_NO_ID), (und_p, H_UND_ID)],
        key=lambda row: (-row[0], row[1]),
    )
    top_prob, top_root_id = ranked[0]
    second_prob = ranked[1][0]
    tie_detected = abs(float(top_prob) - float(second_prob)) <= float(tie_epsilon)

    if tie_detected:
        opinion_root_id = H_UND_ID
        opinion_label = "UNDERDETERMINED"
        opinion_credence = und_p
        reason = "top_two_within_tie_epsilon"
    elif top_root_id == SIMPLE_ROOT_YES_ID:
        opinion_root_id = SIMPLE_ROOT_YES_ID
        opinion_label = "YES"
        opinion_credence = yes_p
        reason = "highest_ledger_probability"
    elif top_root_id == SIMPLE_ROOT_NO_ID:
        opinion_root_id = SIMPLE_ROOT_NO_ID
        opinion_label = "NO"
        opinion_credence = no_p
        reason = "highest_ledger_probability"
    else:
        opinion_root_id = H_UND_ID
        opinion_label = "UNDERDETERMINED"
        opinion_credence = und_p
        reason = "highest_ledger_probability"

    roots = result.roots
    yes_k = float(roots.get(SIMPLE_ROOT_YES_ID, {}).get("k_root", 0.15))
    no_k = float(roots.get(SIMPLE_ROOT_NO_ID, {}).get("k_root", 0.15))
    if opinion_root_id == H_UND_ID:
        opinion_confidence = min(yes_k, no_k)
    else:
        opinion_confidence = float(roots.get(opinion_root_id, {}).get("k_root", min(yes_k, no_k)))

    return {
        "label": opinion_label,
        "root_id": opinion_root_id,
        "credence": float(opinion_credence),
        "confidence": float(opinion_confidence),
        "tie_epsilon": float(tie_epsilon),
        "reason": reason,
        "scores": {
            SIMPLE_ROOT_YES_ID: yes_p,
            SIMPLE_ROOT_NO_ID: no_p,
            H_UND_ID: und_p,
        },
    }


def run_simple_claim_session(
    claim: str,
    deps: RunSessionDeps,
    *,
    credits: Optional[int] = None,
    config: Optional[SessionConfig] = None,
    required_slots: Optional[List[Dict[str, Any]]] = None,
    evidence_items: Optional[List[EvidenceItem]] = None,
    framing: Optional[str] = None,
    run_mode: str = "until_stops",
    policy: Optional[Dict[str, Any]] = None,
) -> SessionResult:
    request = build_simple_claim_request(
        claim,
        credits=credits,
        config=config,
        required_slots=required_slots,
        evidence_items=evidence_items,
        framing=framing,
        run_mode=run_mode,
        policy=policy,
    )
    deps.audit_sink.append(
        AuditEvent(
            "SIMPLE_CLAIM_MODE_USED",
            {
                "profile": SIMPLE_PROFILE,
                "claim": _clean_claim(claim),
                "roots": [SIMPLE_ROOT_YES_ID, SIMPLE_ROOT_NO_ID, H_UND_ID],
                "credits": request.credits,
                "tau": request.config.tau,
            },
        )
    )
    result = run_session(request, deps)
    opinion = _derive_simple_opinion(result, tie_epsilon=float(request.config.epsilon))
    process_confidence = float(opinion.get("confidence", 0.0))
    calibrated_confidence: Optional[float] = None
    policy_map = dict(policy) if isinstance(policy, dict) else {}
    if policy_map:
        calibrated_raw = policy_map.get("calibrated_confidence")
        if isinstance(calibrated_raw, (int, float)):
            calibrated_confidence = float(calibrated_raw)
        elif isinstance(calibrated_raw, str):
            try:
                calibrated_confidence = float(calibrated_raw.strip())
            except ValueError:
                calibrated_confidence = None

    projected_confidence = process_confidence
    if calibrated_confidence is not None:
        projected_confidence = min(projected_confidence, calibrated_confidence)
        if projected_confidence < process_confidence:
            payload = {
                "event": "CONFIDENCE_PROJECTED_CONSERVATIVELY",
                "process_confidence": process_confidence,
                "calibrated_confidence": calibrated_confidence,
                "projected_confidence": projected_confidence,
            }
            deps.audit_sink.append(AuditEvent("CONFIDENCE_PROJECTED_CONSERVATIVELY", payload))
            result.audit.append({"event_type": "CONFIDENCE_PROJECTED_CONSERVATIVELY", "payload": payload})
    opinion["process_confidence"] = float(process_confidence)
    if calibrated_confidence is not None:
        opinion["calibrated_confidence"] = float(calibrated_confidence)
    opinion["confidence"] = float(projected_confidence)
    result.metadata = dict(result.metadata)
    next_steps = result.metadata.get("next_steps", [])
    if not isinstance(next_steps, list):
        next_steps = []
    simple_next_steps = [dict(row) for row in next_steps if isinstance(row, dict)]
    result.metadata["simple_claim"] = {
        "profile": SIMPLE_PROFILE,
        "claim": _clean_claim(claim),
        "scope": request.scope,
        "process_confidence": float(process_confidence),
        "calibrated_confidence": float(calibrated_confidence) if calibrated_confidence is not None else None,
        "opinion": opinion,
        "next_steps": simple_next_steps,
        "defaults": {
            "run_mode": run_mode,
            "credits": request.credits,
            "required_slots": [row.get("slot_key") for row in (request.required_slots or [])],
            "tau": request.config.tau,
            "epsilon": request.config.epsilon,
        },
    }
    deps.audit_sink.append(AuditEvent("SIMPLE_CLAIM_OPINION_DERIVED", dict(opinion)))
    result.audit.append({"event_type": "SIMPLE_CLAIM_OPINION_DERIVED", "payload": dict(opinion)})
    return result
