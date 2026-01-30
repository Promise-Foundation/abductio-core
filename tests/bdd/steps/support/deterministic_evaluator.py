from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicEvaluator:
    script: Dict[str, Any] = field(default_factory=dict)

    def evaluate(
        self,
        node_key: str,
        statement: str = "",
        context: Dict[str, Any] | None = None,
        evidence_items: list | None = None,
    ) -> Dict[str, Any]:
        outcomes = self.script.get("outcomes", {})
        if node_key in outcomes:
            return outcomes[node_key]
        normalized_key = node_key.strip()
        for key, outcome in outcomes.items():
            if isinstance(key, str) and key.strip() == normalized_key:
                return outcome
        child_evaluations = self.script.get("child_evaluations", {})
        if ":" in node_key:
            child_id = node_key.split(":")[-1]
            if child_id in child_evaluations:
                return child_evaluations[child_id]
        return {}
