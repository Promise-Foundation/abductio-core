from __future__ import annotations

import pytest

from abductio_core.adapters.openai_llm import _validate_evaluation, _validate_slot_decomposition


def test_validate_evaluation_accepts_valid_payload() -> None:
    payload = {"p": 0.6, "A": 2, "B": 1, "C": 1, "D": 0, "evidence_refs": "ref1"}
    _validate_evaluation(payload)


def test_validate_evaluation_rejects_missing_fields() -> None:
    payload = {"p": 0.6, "A": 2}
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_evaluation_rejects_bad_ranges() -> None:
    payload = {"p": 1.2, "A": 3, "B": 1, "C": 1, "D": 1, "evidence_refs": "ref1"}
    with pytest.raises(RuntimeError):
        _validate_evaluation(payload)


def test_validate_slot_decomposition_accepts_and_children() -> None:
    payload = {
        "ok": True,
        "type": "AND",
        "coupling": 0.80,
        "children": [
            {"child_id": "c1", "statement": "child 1", "role": "NEC"},
            {"child_id": "c2", "statement": "child 2", "role": "NEC"},
        ],
    }
    _validate_slot_decomposition(payload)


def test_validate_slot_decomposition_rejects_missing_children() -> None:
    payload = {"ok": True, "type": "AND", "coupling": 0.80}
    with pytest.raises(RuntimeError):
        _validate_slot_decomposition(payload)
