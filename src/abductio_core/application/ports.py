from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from abductio_core.domain.audit import AuditEvent
from abductio_core.application.dto import EvidenceItem


class EvaluatorPort(Protocol):
    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: List[EvidenceItem] | None = None,
    ) -> Dict[str, Any]:
        ...


class DecomposerPort(Protocol):
    def decompose(self, target_id: str) -> Dict[str, Any]:
        ...


class AuditSinkPort(Protocol):
    def append(self, event: AuditEvent) -> None:
        ...

class SearchPort(Protocol):
    def search(self, query: str, *, limit: int, metadata: Dict[str, Any]) -> List[EvidenceItem]:
        ...


@dataclass
class RunSessionDeps:
    evaluator: EvaluatorPort
    decomposer: DecomposerPort
    audit_sink: AuditSinkPort
    searcher: SearchPort
