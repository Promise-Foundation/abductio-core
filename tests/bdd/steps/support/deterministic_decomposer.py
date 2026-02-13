from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class DeterministicDecomposer:
    script: Dict[str, Any] = field(default_factory=dict)

    def _min_depth_policy(self) -> int:
        policy = self.script.get("policy", {})
        if not isinstance(policy, dict):
            return 0
        raw = policy.get("min_decomposition_depth_per_slot", 0)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _is_slot_node(target_id: str) -> bool:
        parts = str(target_id or "").split(":")
        return len(parts) == 2 and bool(parts[0]) and bool(parts[1])

    def has_decomposition(self, target_id: str) -> bool:
        slot_decompositions = self.script.get("slot_decompositions", {})
        if target_id in slot_decompositions:
            children = slot_decompositions[target_id].get("children", [])
            return bool(children)
        if self._min_depth_policy() > 0 and self._is_slot_node(target_id):
            return True
        return False

    def decompose(self, root_id: str) -> Dict[str, Any]:
        slot_decompositions = self.script.get("slot_decompositions", {})
        if root_id in slot_decompositions:
            return {
                "ok": True,
                "type": slot_decompositions[root_id].get("type"),
                "coupling": slot_decompositions[root_id].get("coupling"),
                "children": slot_decompositions[root_id].get("children", []),
            }
        if self._min_depth_policy() > 0 and self._is_slot_node(root_id):
            slot_key = root_id.split(":", 1)[1]
            return {
                "ok": True,
                "type": "AND",
                "coupling": 0.80,
                "children": [
                    {
                        "child_id": f"{slot_key}_factor_1",
                        "statement": f"{root_id} factor 1 holds",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": f"Test {root_id} factor 1 with explicit evidence",
                        "overlap_with_siblings": [],
                    },
                    {
                        "child_id": f"{slot_key}_factor_2",
                        "statement": f"{root_id} factor 2 holds",
                        "role": "NEC",
                        "falsifiable": True,
                        "test_procedure": f"Test {root_id} factor 2 with explicit evidence",
                        "overlap_with_siblings": [],
                    },
                ],
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
                "fit_to_key_features_statement": f"{root_id} fits",
                "defeater_statement": f"{root_id} resists defeaters",
                "defeater_resistance_statement": f"{root_id} resists defeaters",
            }

        if isinstance(scope_roots, list):
            for row in scope_roots:
                if row.get("root_id") == root_id:
                    fit_statement = row.get("fit_statement", "")
                    defeater_statement = row.get("defeater_statement", "")
                    return {
                        "ok": True,
                        "feasibility_statement": row.get("feasibility_statement", ""),
                        "availability_statement": row.get("availability_statement", ""),
                        "fit_statement": fit_statement,
                        "fit_to_key_features_statement": row.get("fit_to_key_features_statement", fit_statement),
                        "defeater_statement": defeater_statement,
                        "defeater_resistance_statement": row.get("defeater_resistance_statement", defeater_statement),
                    }
            return {"ok": False}

        scoped_roots = self.script.get("scoped_roots", set())
        if root_id in scoped_roots:
            return {
                "ok": True,
                "feasibility_statement": f"{root_id} is feasible",
                "availability_statement": f"{root_id} is available",
                "fit_statement": f"{root_id} fits",
                "fit_to_key_features_statement": f"{root_id} fits",
                "defeater_statement": f"{root_id} resists defeaters",
                "defeater_resistance_statement": f"{root_id} resists defeaters",
            }

        return {"ok": False}
