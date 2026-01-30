from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core.application.dto import EvidenceItem
from abductio_core.domain.canonical import canonical_id_for_statement


@dataclass
class DeterministicSearcher:
    script: Dict[str, Any] = field(default_factory=dict)

    def search(self, query: str, *, limit: int, metadata: Dict[str, Any]) -> List[EvidenceItem]:
        scripted = self.script.get("responses", {})
        if query in scripted:
            return list(scripted[query])[:limit]
        if self.script.get("autogen", False):
            evidence_id = f"SRCH-{canonical_id_for_statement(query)}"
            return [
                EvidenceItem(
                    id=evidence_id,
                    source="deterministic_searcher",
                    text=f"Search result for: {query}",
                    location={"query": query, "metadata": metadata},
                    metadata={"deterministic": True},
                )
            ][:limit]
        return []
