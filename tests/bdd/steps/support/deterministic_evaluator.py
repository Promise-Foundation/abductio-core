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

        context_strategy = str(self.script.get("context_strategy", "")).strip().lower()
        if context_strategy == "emit_discriminator_from_context":
            ctx = context if isinstance(context, dict) else {}
            contrastive = ctx.get("contrastive") if isinstance(ctx, dict) else None
            if not isinstance(contrastive, dict):
                contrastive = {}
            candidate_ids_raw = contrastive.get("candidate_discriminator_ids")
            if not isinstance(candidate_ids_raw, list):
                candidate_ids_raw = []
            candidate_ids = [str(item).strip() for item in candidate_ids_raw if str(item).strip()]
            primary_pair = str(contrastive.get("primary_pair_key", "")).strip()

            params = self.script.get("context_emitter", {})
            if not isinstance(params, dict):
                params = {}
            p_value = float(params.get("p", 0.72))
            evidence_id = str(params.get("evidence_id", "ref_ctx")).strip() or "ref_ctx"
            if isinstance(evidence_items, list):
                for item in evidence_items:
                    if isinstance(item, dict):
                        candidate_id = str(item.get("id", "")).strip()
                        if candidate_id:
                            evidence_id = candidate_id
                            break

            if candidate_ids:
                discriminator_id = candidate_ids[0]
                return {
                    "p": p_value,
                    "A": 2,
                    "B": 2,
                    "C": 2,
                    "D": 2,
                    "evidence_ids": [evidence_id],
                    "discriminator_ids": [discriminator_id],
                    "discriminator_payloads": [
                        {
                            "id": discriminator_id,
                            "pair": primary_pair,
                            "direction": "FAVORS_LEFT",
                            "evidence_ids": [evidence_id],
                        }
                    ],
                    "non_discriminative": False,
                    "entailment": "SUPPORTS",
                    "evidence_quality": "direct",
                    "reasoning_summary": "BDD context-driven discriminator emission.",
                    "defeaters": ["None noted."],
                    "uncertainty_source": "BDD context strategy.",
                    "assumptions": [],
                }

            return {
                "p": p_value,
                "A": 2,
                "B": 2,
                "C": 2,
                "D": 2,
                "evidence_ids": [evidence_id],
                "discriminator_ids": [],
                "discriminator_payloads": [],
                "non_discriminative": True,
                "entailment": "NEUTRAL",
                "evidence_quality": "direct",
                "reasoning_summary": "BDD context strategy without candidate discriminators.",
                "defeaters": ["None noted."],
                "uncertainty_source": "BDD context strategy.",
                "assumptions": [],
            }

        child_evaluations = self.script.get("child_evaluations", {})
        if ":" in node_key:
            child_id = node_key.split(":")[-1]
            if child_id in child_evaluations:
                return child_evaluations[child_id]
        return {}
