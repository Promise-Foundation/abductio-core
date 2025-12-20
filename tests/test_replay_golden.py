from __future__ import annotations

import json
from pathlib import Path

from abductio_core import replay_session


def test_replay_from_golden_audit_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "audit_golden.json"
    audit = json.loads(fixture_path.read_text())
    result = replay_session(audit).to_dict_view()

    assert result["stop_reason"] == "CREDITS_EXHAUSTED"
    assert abs(result["ledger"]["H1"] - 0.35) <= 1e-9
    assert abs(result["ledger"]["H2"] - 0.45) <= 1e-9
    assert abs(result["ledger"]["H_other"] - 0.20) <= 1e-9
    assert abs(sum(result["ledger"].values()) - 1.0) <= 1e-9
    assert len(result["operation_log"]) == 2
