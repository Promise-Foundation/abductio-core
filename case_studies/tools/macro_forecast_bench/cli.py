from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence


EPS = 1e-12


@dataclass(frozen=True)
class Question:
    question_id: str
    question_text: str
    category: str
    resolution_date: str
    resolved_outcome: int


@dataclass(frozen=True)
class Prediction:
    question_id: str
    p_true: float
    run_id: str
    model_version: str
    produced_at_utc: str


@dataclass(frozen=True)
class EvaluationRecord:
    question_id: str
    question_text: str
    category: str
    resolution_date: str
    outcome: int
    p_true: float
    run_id: str
    model_version: str
    produced_at_utc: str


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_outcome(value: str, *, question_id: str) -> int:
    text = (value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return 1
    if text in {"0", "false", "no", "n"}:
        return 0
    raise ValueError(f"Invalid resolved_outcome {value!r} for question_id={question_id!r}")


def _parse_probability(value: str, *, question_id: str) -> float:
    try:
        p = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid p_true value {value!r} for question_id={question_id!r}") from exc
    if not (0.0 <= p <= 1.0):
        raise ValueError(f"p_true must be in [0,1], got {p} for question_id={question_id!r}")
    return p


def _required_columns(headers: Sequence[str], required: Sequence[str], *, label: str) -> None:
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def load_questions(path: Path) -> Dict[str, Question]:
    if not path.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        _required_columns(
            headers,
            ["question_id", "question_text", "category", "resolution_date", "resolved_outcome"],
            label="questions CSV",
        )
        questions: Dict[str, Question] = {}
        for row in reader:
            question_id = str(row.get("question_id", "")).strip()
            if not question_id:
                raise ValueError("questions CSV contains blank question_id")
            if question_id in questions:
                raise ValueError(f"Duplicate question_id in questions CSV: {question_id}")
            questions[question_id] = Question(
                question_id=question_id,
                question_text=str(row.get("question_text", "")).strip(),
                category=str(row.get("category", "")).strip(),
                resolution_date=str(row.get("resolution_date", "")).strip(),
                resolved_outcome=_parse_outcome(str(row.get("resolved_outcome", "")), question_id=question_id),
            )
    if not questions:
        raise ValueError("questions CSV is empty")
    return questions


def load_predictions(path: Path) -> Dict[str, Prediction]:
    if not path.exists():
        raise FileNotFoundError(f"Predictions file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        _required_columns(headers, ["question_id", "p_true"], label="predictions CSV")
        predictions: Dict[str, Prediction] = {}
        for row in reader:
            question_id = str(row.get("question_id", "")).strip()
            if not question_id:
                raise ValueError("predictions CSV contains blank question_id")
            if question_id in predictions:
                raise ValueError(f"Duplicate question_id in predictions CSV: {question_id}")
            predictions[question_id] = Prediction(
                question_id=question_id,
                p_true=_parse_probability(str(row.get("p_true", "")), question_id=question_id),
                run_id=str(row.get("run_id", "")).strip(),
                model_version=str(row.get("model_version", "")).strip(),
                produced_at_utc=str(row.get("produced_at_utc", "")).strip(),
            )
    if not predictions:
        raise ValueError("predictions CSV is empty")
    return predictions


def build_records(
    questions: Mapping[str, Question], predictions: Mapping[str, Prediction]
) -> List[EvaluationRecord]:
    question_ids = set(questions.keys())
    prediction_ids = set(predictions.keys())
    missing = sorted(question_ids - prediction_ids)
    extra = sorted(prediction_ids - question_ids)
    if missing or extra:
        parts: List[str] = []
        if missing:
            parts.append(f"missing predictions for {missing}")
        if extra:
            parts.append(f"extra predictions for unknown ids {extra}")
        raise ValueError("; ".join(parts))
    records: List[EvaluationRecord] = []
    for question_id in sorted(question_ids):
        q = questions[question_id]
        p = predictions[question_id]
        records.append(
            EvaluationRecord(
                question_id=question_id,
                question_text=q.question_text,
                category=q.category,
                resolution_date=q.resolution_date,
                outcome=q.resolved_outcome,
                p_true=float(p.p_true),
                run_id=p.run_id,
                model_version=p.model_version,
                produced_at_utc=p.produced_at_utc,
            )
        )
    return records


def _log_loss_term(p_true: float, outcome: int) -> float:
    p = min(1.0 - EPS, max(EPS, float(p_true)))
    y = int(outcome)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def _bin_index(value: float, bins: int) -> int:
    if bins <= 0:
        raise ValueError("bins must be > 0")
    clipped = min(1.0 - EPS, max(0.0, float(value)))
    return int(clipped * bins)


def _probability_bins(records: Sequence[EvaluationRecord], bins: int) -> List[Dict[str, Any]]:
    bucket: Dict[int, Dict[str, float]] = {}
    for rec in records:
        idx = _bin_index(rec.p_true, bins)
        row = bucket.setdefault(idx, {"count": 0.0, "sum_p": 0.0, "sum_y": 0.0})
        row["count"] += 1.0
        row["sum_p"] += rec.p_true
        row["sum_y"] += float(rec.outcome)
    rows: List[Dict[str, Any]] = []
    for idx in range(bins):
        stat = bucket.get(idx)
        if not stat:
            continue
        count = int(stat["count"])
        mean_p = stat["sum_p"] / stat["count"]
        observed_rate = stat["sum_y"] / stat["count"]
        rows.append(
            {
                "bin_index": idx,
                "bin_range": f"[{idx / bins:.2f},{(idx + 1) / bins:.2f})",
                "count": count,
                "mean_p_true": mean_p,
                "observed_rate": observed_rate,
                "abs_gap": abs(mean_p - observed_rate),
            }
        )
    return rows


def _confidence_bins(records: Sequence[EvaluationRecord], bins: int) -> List[Dict[str, Any]]:
    bucket: Dict[int, Dict[str, float]] = {}
    for rec in records:
        pred_label = 1 if rec.p_true >= 0.5 else 0
        is_correct = 1 if pred_label == rec.outcome else 0
        conf = max(rec.p_true, 1.0 - rec.p_true)
        idx = _bin_index(conf, bins)
        row = bucket.setdefault(idx, {"count": 0.0, "sum_conf": 0.0, "sum_correct": 0.0})
        row["count"] += 1.0
        row["sum_conf"] += conf
        row["sum_correct"] += float(is_correct)
    rows: List[Dict[str, Any]] = []
    for idx in range(bins):
        stat = bucket.get(idx)
        if not stat:
            continue
        count = int(stat["count"])
        mean_conf = stat["sum_conf"] / stat["count"]
        accuracy = stat["sum_correct"] / stat["count"]
        rows.append(
            {
                "bin_index": idx,
                "bin_range": f"[{idx / bins:.2f},{(idx + 1) / bins:.2f})",
                "count": count,
                "mean_confidence": mean_conf,
                "accuracy": accuracy,
                "abs_gap": abs(mean_conf - accuracy),
            }
        )
    return rows


def evaluate_records(
    records: Sequence[EvaluationRecord],
    *,
    bins: int = 10,
    high_conf_threshold: float = 0.80,
) -> Dict[str, Any]:
    if not records:
        raise ValueError("No evaluation records")
    if not (0.0 <= high_conf_threshold <= 1.0):
        raise ValueError("high_conf_threshold must be in [0,1]")

    n = len(records)
    squared_errors = [(rec.p_true - rec.outcome) ** 2 for rec in records]
    abs_errors = [abs(rec.p_true - rec.outcome) for rec in records]
    log_losses = [_log_loss_term(rec.p_true, rec.outcome) for rec in records]
    predicted_labels = [1 if rec.p_true >= 0.5 else 0 for rec in records]
    correctness = [1 if pred == rec.outcome else 0 for pred, rec in zip(predicted_labels, records)]
    confidences = [max(rec.p_true, 1.0 - rec.p_true) for rec in records]

    brier_score = sum(squared_errors) / n
    log_loss = sum(log_losses) / n
    accuracy = sum(correctness) / n
    event_rate = sum(rec.outcome for rec in records) / n
    mean_p_true = sum(rec.p_true for rec in records) / n
    mean_abs_error = sum(abs_errors) / n
    brier_skill_vs_0_5 = 1.0 - (brier_score / 0.25)

    overconfidence_gaps = [max(0.0, conf - float(ok)) for conf, ok in zip(confidences, correctness)]
    underconfidence_gaps = [max(0.0, float(ok) - conf) for conf, ok in zip(confidences, correctness)]
    high_conf_mask = [conf >= high_conf_threshold for conf in confidences]
    high_conf_total = sum(1 for flag in high_conf_mask if flag)
    high_conf_errors = sum(1 for flag, ok in zip(high_conf_mask, correctness) if flag and ok == 0)
    high_conf_error_rate = (high_conf_errors / high_conf_total) if high_conf_total else 0.0

    prob_bins = _probability_bins(records, bins)
    conf_bins = _confidence_bins(records, bins)
    probability_ece = sum((row["count"] / n) * row["abs_gap"] for row in prob_bins)
    confidence_ece = sum((row["count"] / n) * row["abs_gap"] for row in conf_bins)

    per_question_rows: List[Dict[str, Any]] = []
    for rec, sq_err, lg, ok, conf in zip(records, squared_errors, log_losses, correctness, confidences):
        per_question_rows.append(
            {
                "question_id": rec.question_id,
                "question_text": rec.question_text,
                "category": rec.category,
                "resolution_date": rec.resolution_date,
                "outcome": rec.outcome,
                "p_true": rec.p_true,
                "predicted_label": 1 if rec.p_true >= 0.5 else 0,
                "is_correct": ok,
                "confidence": conf,
                "abs_error": abs(rec.p_true - rec.outcome),
                "squared_error": sq_err,
                "log_loss": lg,
                "run_id": rec.run_id,
                "model_version": rec.model_version,
                "produced_at_utc": rec.produced_at_utc,
            }
        )

    worst = sorted(per_question_rows, key=lambda row: (-row["squared_error"], row["question_id"]))[:5]
    return {
        "metrics": {
            "n": n,
            "accuracy": accuracy,
            "event_rate": event_rate,
            "mean_p_true": mean_p_true,
            "mean_abs_error": mean_abs_error,
            "brier_score": brier_score,
            "brier_skill_vs_0_5": brier_skill_vs_0_5,
            "log_loss": log_loss,
            "probability_ece": probability_ece,
            "confidence_ece": confidence_ece,
            "mean_overconfidence_gap": sum(overconfidence_gaps) / n,
            "mean_underconfidence_gap": sum(underconfidence_gaps) / n,
            "high_conf_threshold": high_conf_threshold,
            "high_conf_fraction": high_conf_total / n,
            "high_conf_error_rate": high_conf_error_rate,
        },
        "probability_bins": prob_bins,
        "confidence_bins": conf_bins,
        "per_question": per_question_rows,
        "worst_questions": worst,
    }


def evaluate_predictions(
    questions_path: Path,
    predictions_path: Path,
    *,
    bins: int = 10,
    high_conf_threshold: float = 0.80,
) -> Dict[str, Any]:
    questions = load_questions(questions_path)
    predictions = load_predictions(predictions_path)
    records = build_records(questions, predictions)
    result = evaluate_records(records, bins=bins, high_conf_threshold=high_conf_threshold)
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "questions_path": str(questions_path),
        "predictions_path": str(predictions_path),
        "bins": bins,
        "high_conf_threshold": high_conf_threshold,
        **result,
    }


def _write_per_question_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    headers = [
        "question_id",
        "category",
        "resolution_date",
        "outcome",
        "p_true",
        "predicted_label",
        "is_correct",
        "confidence",
        "abs_error",
        "squared_error",
        "log_loss",
        "run_id",
        "model_version",
        "produced_at_utc",
        "question_text",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def _render_markdown(result: Mapping[str, Any]) -> str:
    metrics = result["metrics"]
    lines: List[str] = []
    lines.append(f"# Macro Forecast Benchmark Summary ({_now_stamp()})")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- questions: `{result['questions_path']}`")
    lines.append(f"- predictions: `{result['predictions_path']}`")
    lines.append(f"- bins: `{result['bins']}`")
    lines.append(f"- high_conf_threshold: `{result['high_conf_threshold']}`")
    lines.append("")
    lines.append("## Metrics")
    lines.append("| metric | value |")
    lines.append("| --- | --- |")
    for key in [
        "n",
        "accuracy",
        "event_rate",
        "mean_p_true",
        "mean_abs_error",
        "brier_score",
        "brier_skill_vs_0_5",
        "log_loss",
        "probability_ece",
        "confidence_ece",
        "mean_overconfidence_gap",
        "mean_underconfidence_gap",
        "high_conf_fraction",
        "high_conf_error_rate",
    ]:
        value = metrics[key]
        if isinstance(value, float):
            value = _format_float(value)
        lines.append(f"| {key} | {value} |")

    lines.append("")
    lines.append("## Worst Questions (by squared error)")
    lines.append("| question_id | category | outcome | p_true | squared_error |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in result["worst_questions"]:
        lines.append(
            f"| {row['question_id']} | {row['category']} | {row['outcome']} | "
            f"{_format_float(row['p_true'])} | {_format_float(row['squared_error'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def _default_questions_path() -> Path:
    return Path("case_studies/data/macro_forecast_v1/questions.csv")


def _default_results_dir() -> Path:
    return Path("case_studies/data/macro_forecast_v1/results")


def run_evaluate(args: argparse.Namespace) -> Path:
    questions_path = Path(args.questions)
    predictions_path = Path(args.predictions)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    result = evaluate_predictions(
        questions_path=questions_path,
        predictions_path=predictions_path,
        bins=int(args.bins),
        high_conf_threshold=float(args.high_conf_threshold),
    )

    stamp = _now_stamp()
    json_path = outdir / f"{stamp}.json"
    csv_path = outdir / f"{stamp}.csv"
    md_path = outdir / f"{stamp}.md"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_per_question_csv(csv_path, result["per_question"])
    md_path.write_text(_render_markdown(result), encoding="utf-8")
    return md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="macro_forecast_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    eval_parser = sub.add_parser("evaluate", help="Evaluate forecast probabilities against resolved outcomes")
    eval_parser.add_argument("--predictions", required=True, help="CSV with columns question_id,p_true")
    eval_parser.add_argument(
        "--questions",
        default=str(_default_questions_path()),
        help="CSV with resolved benchmark outcomes",
    )
    eval_parser.add_argument(
        "--outdir",
        default=str(_default_results_dir()),
        help="Output directory for JSON/CSV/MD reports",
    )
    eval_parser.add_argument("--bins", type=int, default=10, help="Number of calibration bins")
    eval_parser.add_argument(
        "--high-conf-threshold",
        type=float,
        default=0.80,
        help="Confidence threshold used for high-confidence error-rate checks",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        md_path = run_evaluate(args)
        print(f"macro forecast report: {md_path}")
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2

