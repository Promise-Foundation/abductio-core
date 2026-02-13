from __future__ import annotations

import pytest

from abductio_core.adapters.openai_llm import _validate_evaluation, _validate_slot_decomposition


def test_validate_evaluation_accepts_valid_payload() -> None:
    payload = {
        "p": 0.6,
        "A": 2,
        "B": 1,
        "C": 1,
        "D": 0,
        "evidence_ids": ["EV-1"],
        "discriminator_ids": [],
        "discriminator_payloads": [],
        "entailment": "NEUTRAL",
        "evidence_quality": "direct",
        "reasoning_summary": "Supported by EV-1.",
        "defeaters": ["None observed."],
        "uncertainty_source": "Limited evidence.",
        "assumptions": [],
    }
    _validate_evaluation(payload)


def test_validate_evaluation_rejects_missing_fields() -> None:
    payload = {"p": 0.6, "A": 2}
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_evaluation_rejects_bad_ranges() -> None:
    payload = {
        "p": 1.2,
        "A": 3,
        "B": 1,
        "C": 1,
        "D": 1,
        "evidence_ids": ["EV-1"],
        "discriminator_ids": [],
        "discriminator_payloads": [],
        "entailment": "NEUTRAL",
        "evidence_quality": "direct",
        "reasoning_summary": "Supported by EV-1.",
        "defeaters": ["None observed."],
        "uncertainty_source": "Limited evidence.",
        "assumptions": [],
    }
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_evaluation_rejects_discriminator_payload_mismatch() -> None:
    payload = {
        "p": 0.6,
        "A": 2,
        "B": 1,
        "C": 1,
        "D": 0,
        "evidence_ids": ["EV-1"],
        "discriminator_ids": ["disc:H1|H2"],
        "discriminator_payloads": [
            {
                "id": "disc:OTHER",
                "pair": "H1|H2",
                "direction": "FAVORS_LEFT",
                "evidence_ids": ["EV-1"],
            }
        ],
        "entailment": "SUPPORTS",
        "evidence_quality": "direct",
        "reasoning_summary": "Supported by EV-1.",
        "defeaters": ["None observed."],
        "uncertainty_source": "Limited evidence.",
        "assumptions": [],
    }
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_evaluation_rejects_invalid_entailment() -> None:
    payload = {
        "p": 0.6,
        "A": 2,
        "B": 1,
        "C": 1,
        "D": 0,
        "evidence_ids": ["EV-1"],
        "discriminator_ids": [],
        "discriminator_payloads": [],
        "entailment": "MAYBE",
        "evidence_quality": "direct",
        "reasoning_summary": "Supported by EV-1.",
        "defeaters": ["None observed."],
        "uncertainty_source": "Limited evidence.",
        "assumptions": [],
    }
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_slot_decomposition_accepts_and_children() -> None:
    payload = {
        "ok": True,
        "type": "AND",
        "coupling": 0.80,
        "children": [
            {
                "child_id": "c1",
                "statement": "child 1",
                "role": "NEC",
                "falsifiable": True,
                "test_procedure": "Check child 1",
                "overlap_with_siblings": [],
            },
            {
                "child_id": "c2",
                "statement": "child 2",
                "role": "NEC",
                "falsifiable": True,
                "test_procedure": "Check child 2",
                "overlap_with_siblings": [],
            },
        ],
    }
    _validate_slot_decomposition(payload)


def test_validate_slot_decomposition_rejects_missing_children() -> None:
    payload = {"ok": True, "type": "AND", "coupling": 0.80}
    with pytest.raises(RuntimeError):
        _validate_slot_decomposition(payload)
