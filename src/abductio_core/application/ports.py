from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

from abductio_core.domain.audit import AuditEvent


class EvaluatorPort(Protocol):
    def evaluate(self, node_key: str) -> Dict[str, Any]:
        ...


class DecomposerPort(Protocol):
    def decompose(self, root_id: str) -> Dict[str, Any]:
        ...


class AuditSinkPort(Protocol):
    def append(self, event: AuditEvent) -> None:
        ...


@dataclass
class RunSessionDeps:
    evaluator: EvaluatorPort
    decomposer: DecomposerPort
    audit_sink: AuditSinkPort
