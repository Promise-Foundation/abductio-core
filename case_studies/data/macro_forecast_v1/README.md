# Macro Forecast Benchmark v1 (Minimal)

This is a minimal calibration-focused benchmark for forecast-style questions like:

- "Is the UK economy going to grow next year?"

The goal is not just top-1 plausibility. It is to measure:

- probability quality (`Brier`, `log-loss`),
- calibration (`probability_ece`, `confidence_ece`),
- overconfidence risk (`high_conf_error_rate`, `mean_overconfidence_gap`).

## Files

- `questions.csv`: frozen resolved questions and outcomes.
- `predictions_template.csv`: template for model outputs.
- `results/`: generated evaluation reports (JSON/CSV/MD).

## Important note

`questions.csv` in this starter package is a **synthetic demo set** (`is_synthetic=1`) so the harness can be exercised without external data dependencies.

For production empirical validation:

1. replace outcomes with resolved official series snapshots,
2. freeze source hashes and retrieval timestamps,
3. keep question wording and resolution rules fixed pre-run.

## Run

```bash
.venv/bin/python -m case_studies.tools.macro_forecast_bench evaluate \
  --predictions case_studies/data/macro_forecast_v1/predictions_template.csv \
  --questions case_studies/data/macro_forecast_v1/questions.csv
```

