from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicDecomposer:
    script: Dict[str, Any] = field(default_factory=dict)

    def decompose(self, root_id: str) -> Dict[str, Any]:
        return self.script.get("decompositions", {}).get(root_id, {})
