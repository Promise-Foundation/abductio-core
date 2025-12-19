from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicEvaluator:
    script: Dict[str, Any] = field(default_factory=dict)

    def evaluate(self, node_key: str) -> Dict[str, Any]:
        return self.script.get("outcomes", {}).get(node_key, {})
