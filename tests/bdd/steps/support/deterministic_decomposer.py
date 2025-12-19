from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicDecomposer:
    script: Dict[str, Any] = field(default_factory=dict)

    def decompose(self, root_id: str) -> Dict[str, Any]:
        fail_roots = self.script.get("fail_roots", set())
        if root_id in fail_roots:
            return {"ok": False}

        scope_roots = self.script.get("scope_roots")
        if scope_roots == "all":
            return {
                "ok": True,
                "feasibility_statement": f"{root_id} is feasible",
                "availability_statement": f"{root_id} is available",
                "fit_statement": f"{root_id} fits",
                "defeater_statement": f"{root_id} resists defeaters",
            }

        if isinstance(scope_roots, list):
            for row in scope_roots:
                if row.get("root_id") == root_id:
                    return {
                        "ok": True,
                        "feasibility_statement": row.get("feasibility_statement", ""),
                        "availability_statement": row.get("availability_statement", ""),
                        "fit_statement": row.get("fit_statement", ""),
                        "defeater_statement": row.get("defeater_statement", ""),
                    }
            return {"ok": False}

        return {"ok": False}
