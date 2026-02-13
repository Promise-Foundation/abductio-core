# Safe Baselines

This file records frozen "safe baseline" profiles for historical and ablation runs.

- Profile id: `safe_baseline_v1`
- Policy artifact: `/Users/davidjoseph/github/abductio-core/case_studies/safe_baseline_v1.policy.json`
- Notes: fixed conservative abstention behavior before dynamic abstention mass.
- Profile id: `safe_baseline_v2`
- Policy artifact: `/Users/davidjoseph/github/abductio-core/case_studies/safe_baseline_v2.policy.json`
- Notes: same conservative contract plus pair-adjudication queue and dynamic abstention mass.
- Intended use:
  - Baseline in ablation comparisons.
  - Safety-first reference profile when evaluating new reasoning changes.

Baseline intent:

1. Prefer abstention over unjustified closure.
2. Require typed, contrastive evidence before decisive movement.
3. Enforce active-set adjudication at both scheduling and closure stages.
