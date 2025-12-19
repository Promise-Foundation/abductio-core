from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicEvaluator:
    script: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, node_key: str) -> Dict[str, Any]:
        outcomes = self.script.get("outcomes", {})
        if node_key in outcomes:
            return outcomes[node_key]
        child_evaluations = self.script.get("child_evaluations", {})
        if ":" in node_key:
            child_id = node_key.split(":")[-1]
            if child_id in child_evaluations:
                return child_evaluations[child_id]
        return {}
