from __future__ import annotations

import csv
from pathlib import Path

import pytest

from case_studies.tools.macro_forecast_bench.cli import evaluate_predictions


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_perfect_predictions_metrics(tmp_path: Path) -> None:
    questions = tmp_path / "questions.csv"
    predictions = tmp_path / "predictions.csv"
    _write_csv(
        questions,
        ["question_id", "question_text", "category", "resolution_date", "resolved_outcome"],
        [
            {
                "question_id": "Q1",
                "question_text": "Question 1",
                "category": "gdp_growth",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 1,
            },
            {
                "question_id": "Q2",
                "question_text": "Question 2",
                "category": "inflation",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 0,
            },
        ],
    )
    _write_csv(
        predictions,
        ["question_id", "p_true", "run_id", "model_version", "produced_at_utc"],
        [
            {"question_id": "Q1", "p_true": 0.99, "run_id": "r1", "model_version": "m1", "produced_at_utc": "2026-02-10T00:00:00Z"},
            {"question_id": "Q2", "p_true": 0.01, "run_id": "r1", "model_version": "m1", "produced_at_utc": "2026-02-10T00:00:00Z"},
        ],
    )

    result = evaluate_predictions(questions, predictions, bins=5, high_conf_threshold=0.8)
    metrics = result["metrics"]
    assert metrics["n"] == 2
    assert metrics["accuracy"] == 1.0
    assert metrics["brier_score"] < 0.001
    assert metrics["log_loss"] < 0.02
    assert metrics["high_conf_error_rate"] == 0.0


def test_overconfidence_signal_is_detected(tmp_path: Path) -> None:
    questions = tmp_path / "questions.csv"
    predictions = tmp_path / "predictions.csv"
    _write_csv(
        questions,
        ["question_id", "question_text", "category", "resolution_date", "resolved_outcome"],
        [
            {
                "question_id": "Q1",
                "question_text": "Question 1",
                "category": "gdp_growth",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 1,
            },
            {
                "question_id": "Q2",
                "question_text": "Question 2",
                "category": "gdp_growth",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 0,
            },
        ],
    )
    _write_csv(
        predictions,
        ["question_id", "p_true"],
        [
            {"question_id": "Q1", "p_true": 0.99},
            {"question_id": "Q2", "p_true": 0.99},
        ],
    )

    result = evaluate_predictions(questions, predictions, bins=5, high_conf_threshold=0.8)
    metrics = result["metrics"]
    assert metrics["accuracy"] == 0.5
    assert metrics["high_conf_fraction"] == 1.0
    assert metrics["high_conf_error_rate"] == 0.5
    assert metrics["mean_overconfidence_gap"] > 0.40


def test_missing_prediction_raises(tmp_path: Path) -> None:
    questions = tmp_path / "questions.csv"
    predictions = tmp_path / "predictions.csv"
    _write_csv(
        questions,
        ["question_id", "question_text", "category", "resolution_date", "resolved_outcome"],
        [
            {
                "question_id": "Q1",
                "question_text": "Question 1",
                "category": "gdp_growth",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 1,
            },
            {
                "question_id": "Q2",
                "question_text": "Question 2",
                "category": "gdp_growth",
                "resolution_date": "2024-12-31",
                "resolved_outcome": 0,
            },
        ],
    )
    _write_csv(predictions, ["question_id", "p_true"], [{"question_id": "Q1", "p_true": 0.5}])

    with pytest.raises(ValueError, match="missing predictions"):
        evaluate_predictions(questions, predictions)

