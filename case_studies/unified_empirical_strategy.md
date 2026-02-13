# Unified Empirical Strategy for ABDUCTIO

This is the consolidated strategy for demonstrating ABDUCTIO's effectiveness with defensible, reproducible evidence.
It integrates:
- Normative method constraints from `docs/white_paper.org`
- Executable invariants from `tests/bdd/features/`
- Claim-level study design from `case_studies/abductio_v2_validation_framework.md`
- Dataset-specific protocol constraints under `case_studies/data/*`

## 1) Objective and evidence standard

Primary objective:
Demonstrate that ABDUCTIO is a reliable and useful method for responsible inference under constrained evidence and budget.

Effectiveness is not one metric. It is a stack:
1. Mechanical correctness (invariants always hold).
2. Epistemic quality (calibrated uncertainty, symmetric treatment, anti-inflation behavior).
3. Comparative performance (ABDUCTIO beats ablations and simple baselines under matched inputs).
4. Decision utility (better action quality when plugged into explicit utility models).

## 2) Claim stack mapped to measurable tests

| Claim | Invariant anchor | Experimental anchor | Primary DV | Minimum success criterion |
|---|---|---|---|---|
| 1. Template parity | `02_obligation_template.feature`, `impartiality_symmetry.feature` | Template vs NoTemplate ablation | Winner-flip rate under asymmetric template pressure | Full system has materially lower flip rate than NoTemplate |
| 2. No-free-probability | `04_no_free_probability.feature`, `05_ledger_update_and_other_absorber.feature` | FreeDecomp ablation on decomposability-skew tasks | Free-mass gap (probability movement without paid EVALUATE) | Gap = 0 in invariant runs; significantly smaller than FreeDecomp in experiments |
| 3. Symmetric updates | `10_evaluator_contract_conservative_updates.feature`, `05_ledger_update_and_other_absorber.feature` | Asym-Clipped ablation | Regret vs credits; time-to-crossover after counterevidence | Full system improves regret and crossover behavior |
| 4. VOI-lite scheduling | `06_deterministic_scheduling_and_frontier.feature` | VOI-lite vs MostLikely scheduler | AUC(score vs credits) | VOI-lite outperforms at equal budget |
| 5. (p,k) calibration | `09_confidence_k_rubric.feature`, `11_auditability_and_replay.feature` | Historical + synthetic calibration study | Brier monotonicity by k-bucket | Monotone improvement with increasing k-buckets |
| 6. Decision quality | (Inference/decision separation in white paper) | Utility-based decision tasks | Expected utility / regret | ABDUCTIO-driven policy exceeds baseline policies |

## 3) Unified validation architecture

### Track A: Invariant track (always-on CI gate)
Purpose:
Prove method contract compliance independent of dataset quality.

Inputs:
- `tests/bdd/features/`
- Deterministic decomposer/evaluator/searcher fixtures.

Outputs:
- Pass/fail of each invariant.
- Replay consistency evidence.
- Audit schema conformance checks.

### Track B: Synthetic causal track (ablation engine)
Purpose:
Show that specific ABDUCTIO design choices cause improvements.

Required variants:
- `v2` (full)
- `NoTemplate`
- `FreeDecomp`
- `MostLikely` scheduler
- `Asym-Clipped`

Design:
- Run clean deterministic oracle and noisy/adversarial oracle.
- Keep evaluator calls matched across variants.
- Fixed-credit primary stopping rule.

### Track C: Historical freeze track (Tier 2)
Purpose:
Show performance on realistic, frozen evidence with oracle fallibility handled explicitly.

Current dataset:
- `case_studies/data/UK_AAIB_Reports/`

Required controls:
- Freeze/leakage gates.
- Root-set validation.
- OS class assignment and stratified reporting.
- ABDUCTIO and baselines on identical scope/evidence/roots/budget.

### Track D: Decision track (Tier 3 or late Tier 2)
Purpose:
Show practical value in action selection, not just inference quality.

Requirements:
- Explicit action set.
- Explicit payoff matrix.
- Pre-registered decision policy.
- Resolved outcomes for scoring utility/regret.

## 4) Hard gates before claiming results

### Gate 0: Spec consistency lock
Before new claim reporting, normalize these cross-document mismatches:
1. Operation set mismatch: `03_cost_model_and_ops.feature` says 2 operations while white paper and `13_evidence_search.feature` use 3 (`DECOMPOSE`, `EVALUATE`, `SEARCH`).
2. Credit model mismatch: features treat each operation as cost 1, while white paper includes dynamic decomposition cost.
3. Slot template mismatch: white paper required slots omit `feasibility`, while parts of code/docs still include it.
4. Open-world residual mismatch: `H_NOA/H_UND` vs `H_OTHER` conventions.
5. Oracle-strength notation mismatch: legacy `OS-A/B/C` references vs canonical `OS-1..OS-5`.

Gate 0 output:
- A single locked "protocol profile" for this repo version.
- Changelog noting any deferred mismatches and why.

### Gate 1: Evaluator reliability
Use canonical thresholds from `case_studies/abductio_v2_validation_framework.md`:
- ICC(p) >= 0.70 (human), ICC(p) >= 0.90 (deterministic LLM).
- k-bucket agreement >= 70% exact or +/-1 bucket.

### Gate 2: Data validity and leakage controls
Per dataset build:
- Leakage audit report.
- Evidence hashes and provenance.
- Root-set validation artifacts.
- Schema validation pass.

## 5) Minimum artifact contract per run

Each run must publish:
1. `run_meta.json` (commit hash, model/version, seed/temperature, config hash).
2. Input snapshot hashes (evidence packet, roots, oracle mapping policy).
3. `request.json` and `result.json`.
4. Full `audit_trace.json` with operation-level arithmetic.
5. Credit ledger by operation type and target.
6. `results.json` with primary/secondary DVs and confidence intervals.

Each claim report must publish:
1. Primary effect size + 95% CI.
2. Secondary effects.
3. Stress-oracle sensitivity.
4. OS-stratified historical results.
5. Failure modes and null results.

## 6) Statistical and reporting policy

1. One primary test per claim, pre-registered.
2. Mixed-effects models with problem and evaluator random effects where applicable.
3. Effect sizes and confidence intervals are primary evidence.
4. p-values are secondary.
5. Multiple-comparisons handling is pre-declared.
6. Tier-specific inclusion/exclusion rules are frozen before analysis.

## 7) Execution plan (recommended sequence)

### Phase 0 (immediate)
1. Complete Gate 0 consistency lock.
2. Run invariant suite and freeze passing baseline.
3. Run evaluator reliability pack and lock evaluator profile.

### Phase 1 (synthetic first)
1. Execute ablation suite on synthetic datasets.
2. Evaluate Claims 2, 3, and 4 first (cleanest causal attribution).
3. Publish score-vs-credits and regret plots.

### Phase 2 (historical AAIB)
1. Build/validate corpus cases with leakage and schema checks.
2. Run ABDUCTIO and baselines with matched budget/evaluator setup.
3. Evaluate Claim 5 (calibration) and supporting agreement metrics.

### Phase 3 (decision quality)
1. Add utility-grounded tasks with resolved outcomes.
2. Evaluate Claim 6 (expected utility/regret).
3. Publish decision policy sensitivity analysis.

## 8) What "effective" should mean in final reporting

ABDUCTIO should be presented as effective only if all are true:
1. Invariants pass continuously.
2. Ablations show the architecture choices matter.
3. Historical frozen-evidence results show calibrated, robust behavior.
4. Decision-layer experiments show utility gains, not just score gains.
5. All results are reproducible from published artifacts and hashes.
