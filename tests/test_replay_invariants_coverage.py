from __future__ import annotations

from abductio_core.application.use_cases.replay_session import replay_session
from abductio_core.domain.invariants import H_NOA_ID, H_UND_ID, enforce_open_world


def test_replay_handles_non_dict_payload_and_bad_stop_reason() -> None:
    audit = [
        {"event_type": "SESSION_INITIALIZED", "payload": {"roots": ["H1", "H_NOA", "H_UND"], "ledger": {"H1": 0.3, "H_NOA": 0.35, "H_UND": 0.35}}},
        {"event_type": "STOP_REASON_RECORDED", "payload": {"stop_reason": "NOT_A_REASON"}},
        {"event_type": "OP_EXECUTED", "payload": "bad"},
    ]
    result = replay_session(audit).to_dict_view()
    assert result["stop_reason"] is None


def test_enforce_open_world_zero_named() -> None:
    ledger = {H_NOA_ID: 0.0, H_UND_ID: 0.0}
    out = enforce_open_world(ledger, [])
    assert out[H_NOA_ID] == 0.5
    assert out[H_UND_ID] == 0.5
