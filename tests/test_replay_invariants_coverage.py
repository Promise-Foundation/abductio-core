from __future__ import annotations

from abductio_core.application.use_cases.replay_session import replay_session
from abductio_core.domain.invariants import H_OTHER_ID, enforce_absorber


def test_replay_handles_non_dict_payload_and_bad_stop_reason() -> None:
    audit = [
        {"event_type": "SESSION_INITIALIZED", "payload": {"roots": ["H1", "H_other"], "ledger": {"H1": 0.3, "H_other": 0.7}}},
        {"event_type": "STOP_REASON_RECORDED", "payload": {"stop_reason": "NOT_A_REASON"}},
        {"event_type": "OP_EXECUTED", "payload": "bad"},
    ]
    result = replay_session(audit).to_dict_view()
    assert result["stop_reason"] is None


def test_enforce_absorber_zero_named() -> None:
    ledger = {H_OTHER_ID: 0.0}
    out = enforce_absorber(ledger, [])
    assert out[H_OTHER_ID] == 1.0
