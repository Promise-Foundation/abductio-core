from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicDecomposer:
    script: Dict[str, Any] = field(default_factory=dict)

    def decompose(self, root_id: str) -> Dict[str, Any]:
        slot_decompositions = self.script.get("slot_decompositions", {})
        if root_id in slot_decompositions:
            return {
                "ok": True,
                "type": slot_decompositions[root_id].get("type"),
                "coupling": slot_decompositions[root_id].get("coupling"),
                "children": slot_decompositions[root_id].get("children", []),
            }

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

        scoped_roots = self.script.get("scoped_roots", set())
        if root_id in scoped_roots:
            return {
                "ok": True,
                "feasibility_statement": f"{root_id} is feasible",
                "availability_statement": f"{root_id} is available",
                "fit_statement": f"{root_id} fits",
                "defeater_statement": f"{root_id} resists defeaters",
            }

        return {"ok": False}
