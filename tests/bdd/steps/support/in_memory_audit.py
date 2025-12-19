from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from abductio_core.domain.audit import AuditEvent


@dataclass
class InMemoryAuditSink:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)
