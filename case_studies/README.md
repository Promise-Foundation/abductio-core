# ABDUCTIO Case Studies

This folder is the validation workspace for demonstrating ABDUCTIO empirically.
Use this file as the entrypoint for methodology, dataset protocols, and run/review workflows.

## Read order (canonical path)
1. `case_studies/unified_empirical_strategy.md`
2. `case_studies/abductio_v2_validation_framework.md`
3. `docs/white_paper.org`
4. `tests/bdd/features/`
5. Dataset protocol for your corpus, for example:
   - `case_studies/data/UK_AAIB_Reports/methodology.org`
   - `case_studies/data/UK_AAIB_Reports/spec/`
6. `case_studies/reviewer_guide.md` for operational build/review steps

## Authority map
- `docs/white_paper.org`: normative inference design and invariants.
- `tests/bdd/features/`: executable behavioral contract; CI-level invariants.
- `case_studies/abductio_v2_validation_framework.md`: claim-level experimental design and reporting requirements.
- `case_studies/unified_empirical_strategy.md`: consolidated execution plan across invariants, synthetic validation, historical datasets, and decision-quality studies.
- `case_studies/data/*/methodology.org` + `case_studies/data/*/spec/`: dataset-specific freeze, leakage, oracle, and schema rules.

## Document roles in this repo
- `case_studies/validation_overview.md`: short orientation and high-level checklist.
- `case_studies/case_study_methodology.org`: extended methodology rationale (supplemental).
- `case_studies/baselines/`: baseline method definitions to run under identical scope/evidence/budget.

## Practical workflow
1. Lock the claim and preregistration fields in `case_studies/abductio_v2_validation_framework.md`.
2. Validate invariants by running BDD and core tests (`tests/bdd/features/` and `tests/`).
3. Build/validate historical cases using dataset tooling (AAIB toolchain in `case_studies/tools/aaib_bench/`).
4. Run ABDUCTIO + baselines with matched evaluator calls and fixed budgets.
5. Publish per-run artifacts and claim-level result tables with confidence intervals.

## Staged historical backtest quickstart
Use the AAIB CLI to run a leakage-safe staged historical proxy backtest (T0/T1/T2/T3) with a locked holdout year:

```bash
PYTHONPATH=src .venv/bin/python -m case_studies.tools.aaib_bench.aaib_bench historical-backtest \
  --case Boeing_737-8AS_9H-QAA_12-25 \
  --holdout-year 2024 \
  --locked-policy-profile boeing_inference_v1 \
  --credits 10
```

Outputs are written to `case_studies/data/UK_AAIB_Reports/results/backtest/` as JSON/CSV reports.

## Historical ablation suite quickstart
Run frozen staged packets through cumulative ABDUCTIO variants:
`baseline -> pair_engine -> dynamic_und -> composition`.

```bash
PYTHONPATH=src .venv/bin/python -m case_studies.tools.aaib_bench.aaib_bench historical-ablation \
  --case Boeing_737-8AS_9H-QAA_12-25 \
  --holdout-year 2024 \
  --locked-policy-profile boeing_inference_v1 \
  --credits 10
```

The ablation report includes per-variant top-1 accuracy, calibration
(`mean_brier`/`mean_log_loss`), abstention rate, and abstention-honesty rate,
plus deltas relative to baseline.

## Macro forecast benchmark quickstart
Use the minimal macro-forecast harness to evaluate calibration and overconfidence
for questions such as "Is the UK economy going to grow next year?":

```bash
.venv/bin/python -m case_studies.tools.macro_forecast_bench evaluate \
  --predictions case_studies/data/macro_forecast_v1/predictions_template.csv \
  --questions case_studies/data/macro_forecast_v1/questions.csv
```

Outputs are written to `case_studies/data/macro_forecast_v1/results/` as JSON/CSV/MD reports.
