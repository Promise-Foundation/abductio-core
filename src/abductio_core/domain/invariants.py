from __future__ import annotations

from typing import Dict, Iterable


H_OTHER_ID = "H_other"


def enforce_absorber(ledger: Dict[str, float], named_root_ids: Iterable[str]) -> Dict[str, float]:
    named_ids = list(named_root_ids)
    sum_named = sum(ledger.get(root_id, 0.0) for root_id in named_ids)
    if sum_named <= 1.0:
        ledger[H_OTHER_ID] = 1.0 - sum_named
        return ledger

    if sum_named == 0.0:
        ledger[H_OTHER_ID] = 1.0
        return ledger

    for root_id in named_ids:
        ledger[root_id] = ledger.get(root_id, 0.0) / sum_named
    ledger[H_OTHER_ID] = 0.0
    return ledger
