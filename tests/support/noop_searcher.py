from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from abductio_core.application.dto import EvidenceItem


@dataclass
class NoopSearcher:
    def search(self, query: str, *, limit: int, metadata: Dict[str, Any]) -> List[EvidenceItem]:
        return []
