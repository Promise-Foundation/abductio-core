from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StopReason(str, Enum):
    CREDITS_EXHAUSTED = "CREDITS_EXHAUSTED"
    FRONTIER_CONFIDENT = "FRONTIER_CONFIDENT"


@dataclass
class SessionResult:
    roots: Dict[str, Dict[str, Any]]
    ledger: Dict[str, float]
    audit: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: Optional[StopReason] = None
    credits_remaining: int = 0
    total_credits_spent: int = 0
    operation_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict_view(self) -> Dict[str, Any]:
        return {
            "roots": self.roots,
            "ledger": self.ledger,
            "audit": list(self.audit),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "credits_remaining": self.credits_remaining,
            "total_credits_spent": self.total_credits_spent,
            "operation_log": list(self.operation_log),
        }
