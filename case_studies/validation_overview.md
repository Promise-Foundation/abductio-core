# ABDUCTIO Validation Overview

Use this file as a quick orientation only.
The canonical execution strategy is in `case_studies/unified_empirical_strategy.md`.

## Validation goal
Demonstrate that ABDUCTIO is:
1. Mechanically correct (invariants and replayability).
2. Epistemically responsible (calibrated uncertainty, symmetry, anti-inflation behavior).
3. Empirically competitive (beats ablations and simple baselines under matched inputs).
4. Decision-useful (improves expected utility when mapped to actions).

## Canonical document stack
1. `case_studies/unified_empirical_strategy.md` (consolidated strategy and execution sequence).
2. `case_studies/abductio_v2_validation_framework.md` (claim-level preregistration and reporting requirements).
3. `docs/white_paper.org` + `tests/bdd/features/` (method contract: normative + executable).
4. Dataset-specific protocols under `case_studies/data/*`.

## Required prerequisites
1. Gate 0 spec consistency lock (operation set, credit model, slot template, open-world naming, oracle class notation).
2. Evaluator reliability gate (per canonical thresholds in `case_studies/abductio_v2_validation_framework.md`).
3. Evidence freeze and leakage controls for historical datasets.

## Required outputs per case/run
1. Frozen evidence packet, roots, oracle mapping artifact, and hashes.
2. Full run artifacts (`request.json`, `result.json`, `audit_trace.json`, credit ledger).
3. `results.json` with pre-registered primary/secondary metrics.
4. Baseline comparison outputs under identical scope/evidence/budget.

## Interpretation policy
- Oracle agreement metrics are reported as agreement with a later inference state, not truth.
- Label-independent metrics (auditability, uncertainty discipline, robustness) are first-class.
- Disagreement with oracle must be classified and justified using explicit evidence references and confidence bounds.
