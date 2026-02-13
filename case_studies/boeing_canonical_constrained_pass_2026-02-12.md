# Boeing Canonical Constrained Pass (2026-02-12)

## Objective
Run Boeing validation under constrained rules:
- No methodology-divergent extensions (asymmetric hunter/judge, retirement, directional linker, etc.).
- Fix wiring/conformance defects only.
- Improve representation only (root-set clarity and evidence typing tags), not update math.

## Changes Applied
1. Policy wiring alias in engine:
   - Accept `pair_value_prioritization_enabled` as alias for
     `pair_adjudication_value_prioritization_enabled`.
2. Locked profile reset to canonical-safe settings:
   - `case_studies/boeing_inference_v1.policy.json` now matches conservative certify-mode contract.
3. Boeing-specific root-set refinement:
   - Added `AAIB_GROUND_COLLISION_S1_boeing_v2` in roots libraries.
   - Updated Boeing case `roots.yaml` to use the v2 set.
4. Evidence representation enrichment:
   - Added neutral `metadata.typing_tags` to key Boeing history items in `evidence_packet.json`.

## Validation Runs
All runs used:
- Case: `Boeing_737-8AS_9H-QAA_12-25`
- Holdout year: `2024`
- Locked profile: `boeing_inference_v1`
- Method: `abductio`
- Model: `gpt-4.1-mini`

### Reports
- Credits 10: `case_studies/data/UK_AAIB_Reports/results/backtest/20260212T115320Z.json`
- Credits 30: `case_studies/data/UK_AAIB_Reports/results/backtest/20260212T120952Z.json`
- Credits 60: `case_studies/data/UK_AAIB_Reports/results/backtest/20260212T131645Z.json`

## Outcome Summary
- `top1_accuracy` remained `0.0` at all stages for all budgets.
- Top contender remained `H_UND` at all stages for all budgets.
- Stop reason remained `CREDITS_EXHAUSTED` in all rows.

### Stage tops by budget
- Credits 10:
  - T0: H_UND (0.324)
  - T1: H_UND (0.244)
  - T2: H_UND (0.408)
  - T3: H_UND (0.287)
- Credits 30:
  - T0: H_UND (0.491)
  - T1: H_UND (0.289)
  - T2: H_UND (0.237)
  - T3: H_UND (0.277)
- Credits 60:
  - T0: H_UND (0.243)
  - T1: H_UND (0.241)
  - T2: H_UND (0.246)
  - T3: H_UND (0.252)

### Canonicality check
In the 60-credit run, all stages had zero counts for extension-specific events:
- `HUNTER_SEARCH_LOAN_GRANTED`
- `JUDGE_VERIFICATION_REQUIRED`
- `CONTENDER_RETIRED`
- `TYPED_DIRECTIONAL_EVIDENCE_CONFLICT`
- `PAIR_VALUE_PRIORITY_COMPUTED`

This confirms the constrained/canonical profile was active.

## Bottom Line
Under canonical Abductio settings, with representation tightened and credits increased to 60,
Boeing winner recovery still did not occur. The bottleneck appears to persist in decisive
contrastive resolution under budget, not in the specific extension mechanisms that were turned off.
