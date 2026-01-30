from __future__ import annotations

from typing import Dict, Iterable


H_NOA_ID = "H_NOA"
H_UND_ID = "H_UND"


def enforce_open_world(ledger: Dict[str, float], named_root_ids: Iterable[str]) -> Dict[str, float]:
    named_ids = list(named_root_ids)
    sum_named = sum(ledger.get(root_id, 0.0) for root_id in named_ids)
    if sum_named == 0.0:
        ledger[H_NOA_ID] = 0.5
        ledger[H_UND_ID] = 0.5
        return ledger
    if sum_named <= 1.0:
        remainder = 1.0 - sum_named
        # Preserve existing NOA/UND split if present, otherwise split evenly.
        noa = ledger.get(H_NOA_ID)
        und = ledger.get(H_UND_ID)
        if noa is None or und is None or noa + und <= 0.0:
            ledger[H_NOA_ID] = remainder / 2.0
            ledger[H_UND_ID] = remainder / 2.0
        else:
            scale = remainder / (noa + und)
            ledger[H_NOA_ID] = noa * scale
            ledger[H_UND_ID] = und * scale
        return ledger

    for root_id in named_ids:
        ledger[root_id] = ledger.get(root_id, 0.0) / sum_named
    ledger[H_NOA_ID] = 0.0
    ledger[H_UND_ID] = 0.0
    return ledger
