from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from case_studies.tools.aaib_bench.aaib_bench import backtest


def _write_index(path: Path, rows: list[dict[str, str]]) -> None:
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    (root / "spec").mkdir(parents=True)
    (root / "results").mkdir(parents=True)
    monkeypatch.setenv("AAIB_CORPUS_ROOT", str(root))
    (root / "spec" / "leakage_checks.md").write_text(
        "## Disallowed language detector (soft gate)\n- concluded\n- probable\n",
        encoding="utf-8",
    )
    return root


def test_build_stage_packets_progressive() -> None:
    packet = {
        "case_id": "sample",
        "items": [
            {"id": "H1", "source": "history", "text": "h1"},
            {"id": "H2", "source": "history", "text": "h2"},
            {"id": "H3", "source": "history", "text": "h3"},
            {"id": "H4", "source": "history", "text": "h4"},
            {"id": "H5", "source": "history", "text": "h5"},
            {"id": "H6", "source": "history", "text": "h6"},
            {"id": "S1", "source": "synopsis", "text": "s1"},
            {"id": "S2", "source": "synopsis", "text": "s2"},
        ],
    }
    stages = backtest.build_stage_packets(packet)
    assert [stage["stage_id"] for stage in stages] == [
        "T0_PRELIM",
        "T1_EARLY",
        "T2_INTERIM",
        "T3_PREFINAL",
    ]
    assert [stage["item_count"] for stage in stages] == [2, 4, 6, 8]
    assert all(stage["stage_selection_mode"] == "section_progressive" for stage in stages)


def test_aggregate_stage_metrics() -> None:
    rows = [
        {
            "status": "ok",
            "method": "abductio",
            "stage_id": "T0_PRELIM",
            "stage_index": 0,
            "oracle_eval_eligible": True,
            "top1_match": True,
            "oracle_in_top_tie": False,
            "top1_ambiguous": False,
            "top_root_p": 0.70,
            "oracle_target_p": 0.70,
            "brier": 0.20,
            "log_loss": 0.30,
        },
        {
            "status": "ok",
            "method": "abductio",
            "stage_id": "T0_PRELIM",
            "stage_index": 0,
            "oracle_eval_eligible": True,
            "top1_match": False,
            "oracle_in_top_tie": True,
            "top1_ambiguous": True,
            "top_root_p": 0.60,
            "oracle_target_p": 0.40,
            "brier": 0.40,
            "log_loss": 0.90,
        },
    ]
    aggregates = backtest.aggregate_stage_metrics(rows)
    assert len(aggregates) == 1
    stage = aggregates[0]
    assert stage["stage_id"] == "T0_PRELIM"
    assert stage["top1_accuracy"] == 0.5
    assert stage["top1_or_tie_hit_rate"] == 1.0
    assert stage["ambiguous_rate"] == 0.5
    assert stage["mean_oracle_target_p"] == 0.55


def test_run_historical_backtest_holdout_only(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "dev_case",
                "date_utc": "2024-01-10",
                "selected_for_corpus": "Y",
            },
            {
                "case_id": "holdout_case",
                "date_utc": "2025-01-10",
                "selected_for_corpus": "Y",
            },
        ],
    )
    for case_id in ("dev_case", "holdout_case"):
        case_dir = corpus / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        packet = {
            "case_id": case_id,
            "evidence_freeze_time_utc": "2026-01-01",
            "pdf_sha256": "abc",
            "items": [
                {"id": "S1", "source": "synopsis", "text": "factual item"},
                {"id": "H1", "source": "history", "text": "factual item"},
                {"id": "H2", "source": "history", "text": "factual item"},
            ],
        }
        (case_dir / "evidence_packet.json").write_text(json.dumps(packet) + "\n", encoding="utf-8")
        (case_dir / "answer_key.md").write_text(
            "# Answer key\n\n- oracle_root_id: R1\n",
            encoding="utf-8",
        )
        (case_dir / "roots.yaml").write_text(
            "\n".join(
                [
                    f"case_id: {case_id}",
                    "root_set_id: TEST_SET",
                    "roots:",
                    "  - id: R1",
                    "  - id: R2",
                    "  - id: H_OTHER",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    call_log: list[dict[str, object]] = []

    def fake_run_case(
        case_id: str,
        credits: int = 10,
        model: str = "gpt-4.1-mini",
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        strict_mece: bool | None = None,
        max_pair_overlap: float | None = None,
        hardened_one_shot: bool = False,
        policy_profile_id: str | None = None,
        enforce_policy_preflight: bool = False,
        evidence_items_override: list[dict[str, object]] | None = None,
        run_tag: str | None = None,
        extra_meta: dict[str, object] | None = None,
    ) -> Path:
        call_log.append(
            {
                "case_id": case_id,
                "strict_mece": strict_mece,
                "max_pair_overlap": max_pair_overlap,
                "hardened_one_shot": hardened_one_shot,
                "policy_profile_id": policy_profile_id,
                "enforce_policy_preflight": enforce_policy_preflight,
                "run_tag": run_tag,
            }
        )
        run_root = corpus / "cases" / case_id / "runs" / "abductio"
        run_root.mkdir(parents=True, exist_ok=True)
        run_dir = run_root / (run_tag or "run")
        run_dir.mkdir(parents=True, exist_ok=True)
        item_count = len(evidence_items_override or [])
        top_root = "R1" if item_count >= 2 else "R2"
        result = {
            "ledger": {"R1": 0.7 if top_root == "R1" else 0.2, "R2": 0.2 if top_root == "R1" else 0.7},
            "stop_reason": "TEST_STOP",
            "total_credits_spent": credits,
        }
        (run_dir / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
        return run_dir

    monkeypatch.setattr(backtest, "run_case", fake_run_case)

    report_path = backtest.run_historical_backtest(
        case_ids=["dev_case", "holdout_case"],
        holdout_year=2025,
        run_dev=False,
        selected_only=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report["rows"]
    assert rows
    assert {row["case_id"] for row in rows} == {"holdout_case"}
    assert all(row["split"] == "holdout" for row in rows if row.get("status") == "ok")
    assert call_log
    assert all(entry["strict_mece"] is None for entry in call_log)
    assert all(entry["max_pair_overlap"] is None for entry in call_log)
    assert report["mode"] == "staged_historical_proxy_v2"
    assert "provenance" in report
    summary_path = report_path.with_suffix(".md")
    assert summary_path.exists()
    summary = summary_path.read_text(encoding="utf-8")
    assert "AAIB Historical Backtest Summary" in summary
    assert "aaib_bench_version" in summary


def test_run_historical_backtest_propagates_mece_overrides(corpus: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "holdout_case",
                "date_utc": "2025-01-10",
                "selected_for_corpus": "Y",
            },
        ],
    )
    case_dir = corpus / "cases" / "holdout_case"
    case_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "case_id": "holdout_case",
        "evidence_freeze_time_utc": "2026-01-01",
        "pdf_sha256": "abc",
        "items": [
            {"id": "S1", "source": "synopsis", "text": "factual item"},
            {"id": "H1", "source": "history", "text": "factual item"},
        ],
    }
    (case_dir / "evidence_packet.json").write_text(json.dumps(packet) + "\n", encoding="utf-8")
    (case_dir / "answer_key.md").write_text("# Answer key\n\n- oracle_root_id: R1\n", encoding="utf-8")
    (case_dir / "roots.yaml").write_text(
        "\n".join(
            [
                "case_id: holdout_case",
                "root_set_id: TEST_SET",
                "roots:",
                "  - id: R1",
                "  - id: R2",
                "  - id: H_OTHER",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    call_log: list[dict[str, object]] = []

    def fake_run_case(
        case_id: str,
        credits: int = 10,
        model: str = "gpt-4.1-mini",
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        strict_mece: bool | None = None,
        max_pair_overlap: float | None = None,
        hardened_one_shot: bool = False,
        policy_profile_id: str | None = None,
        enforce_policy_preflight: bool = False,
        evidence_items_override: list[dict[str, object]] | None = None,
        run_tag: str | None = None,
        extra_meta: dict[str, object] | None = None,
    ) -> Path:
        call_log.append(
            {
                "case_id": case_id,
                "strict_mece": strict_mece,
                "max_pair_overlap": max_pair_overlap,
                "hardened_one_shot": hardened_one_shot,
                "policy_profile_id": policy_profile_id,
                "enforce_policy_preflight": enforce_policy_preflight,
            }
        )
        run_root = corpus / "cases" / case_id / "runs" / "abductio"
        run_root.mkdir(parents=True, exist_ok=True)
        run_dir = run_root / (run_tag or "run")
        run_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "ledger": {"R1": 0.7, "R2": 0.2},
            "stop_reason": "TEST_STOP",
            "total_credits_spent": credits,
        }
        (run_dir / "result.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
        return run_dir

    monkeypatch.setattr(backtest, "run_case", fake_run_case)

    report_path = backtest.run_historical_backtest(
        case_ids=["holdout_case"],
        holdout_year=2025,
        strict_mece=True,
        max_pair_overlap=0.5,
        selected_only=True,
    )
    assert report_path.exists()
    assert call_log
    assert all(entry["strict_mece"] is True for entry in call_log)
    assert all(entry["max_pair_overlap"] == 0.5 for entry in call_log)


def test_run_historical_backtest_requires_locked_policy_for_boeing_case(
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "Boeing_737-8AS_9H-QAA_12-25",
                "date_utc": "2025-01-10",
                "selected_for_corpus": "Y",
            },
        ],
    )
    case_dir = corpus / "cases" / "Boeing_737-8AS_9H-QAA_12-25"
    case_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "case_id": "Boeing_737-8AS_9H-QAA_12-25",
        "evidence_freeze_time_utc": "2026-01-01",
        "pdf_sha256": "abc",
        "items": [
            {"id": "S1", "source": "synopsis", "text": "factual item"},
            {"id": "H1", "source": "history", "text": "factual item"},
        ],
    }
    (case_dir / "evidence_packet.json").write_text(json.dumps(packet) + "\n", encoding="utf-8")
    (case_dir / "answer_key.md").write_text("# Answer key\n\n- oracle_root_id: R1\n", encoding="utf-8")
    (case_dir / "roots.yaml").write_text(
        "\n".join(
            [
                "case_id: Boeing_737-8AS_9H-QAA_12-25",
                "root_set_id: TEST_SET",
                "roots:",
                "  - id: R1",
                "  - id: R2",
                "  - id: H_OTHER",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(backtest, "run_case", lambda **_: (_ for _ in ()).throw(AssertionError("run_case should not execute")))

    report_path = backtest.run_historical_backtest(
        case_ids=["Boeing_737-8AS_9H-QAA_12-25"],
        holdout_year=2025,
        selected_only=True,
        methods=["abductio"],
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report.get("rows", [])
    assert rows
    assert all(row.get("status") == "error" for row in rows)
    assert any("Locked policy profile required" in str(row.get("error", "")) for row in rows)


def test_run_historical_backtest_applies_locked_profile_with_preflight(
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "Boeing_737-8AS_9H-QAA_12-25",
                "date_utc": "2025-01-10",
                "selected_for_corpus": "Y",
            },
        ],
    )
    case_dir = corpus / "cases" / "Boeing_737-8AS_9H-QAA_12-25"
    case_dir.mkdir(parents=True, exist_ok=True)
    packet = {
        "case_id": "Boeing_737-8AS_9H-QAA_12-25",
        "evidence_freeze_time_utc": "2026-01-01",
        "pdf_sha256": "abc",
        "items": [
            {"id": "S1", "source": "synopsis", "text": "factual item"},
            {"id": "H1", "source": "history", "text": "factual item"},
        ],
    }
    (case_dir / "evidence_packet.json").write_text(json.dumps(packet) + "\n", encoding="utf-8")
    (case_dir / "answer_key.md").write_text("# Answer key\n\n- oracle_root_id: R1\n", encoding="utf-8")
    (case_dir / "roots.yaml").write_text(
        "\n".join(
            [
                "case_id: Boeing_737-8AS_9H-QAA_12-25",
                "root_set_id: TEST_SET",
                "roots:",
                "  - id: R1",
                "  - id: R2",
                "  - id: H_OTHER",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    call_log: list[dict[str, object]] = []

    def fake_run_case(**kwargs: object) -> Path:
        call_log.append(dict(kwargs))
        run_root = case_dir / "runs" / "abductio"
        run_root.mkdir(parents=True, exist_ok=True)
        run_dir = run_root / "locked_profile_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "ledger": {"R1": 0.7, "R2": 0.2},
                    "stop_reason": "TEST_STOP",
                    "total_credits_spent": int(kwargs.get("credits", 0)),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

    monkeypatch.setattr(backtest, "run_case", fake_run_case)

    report_path = backtest.run_historical_backtest(
        case_ids=["Boeing_737-8AS_9H-QAA_12-25"],
        holdout_year=2025,
        selected_only=True,
        methods=["abductio"],
        locked_policy_profile="boeing_inference_v1",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report.get("rows", [])
    assert rows
    assert all(row.get("status") == "ok" for row in rows)
    assert call_log
    assert all(str(call.get("policy_profile_id", "")) == "boeing_inference_v1" for call in call_log)
    assert all(bool(call.get("enforce_policy_preflight")) for call in call_log)
    assert all(
        bool((call.get("policy_override", {}) or {}).get("pair_resolution_engine_enabled"))
        for call in call_log
    )


def test_run_historical_ablation_suite_aggregates_variants(
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_historical_backtest(**kwargs: object) -> Path:
        ablation_label = str(kwargs.get("ablation_label", "")).strip()
        policy_override = kwargs.get("abductio_policy_override")
        calls.append(
            {
                "ablation_label": ablation_label,
                "policy_override_type": type(policy_override).__name__,
            }
        )

        is_baseline = ablation_label == "baseline"
        row = {
            "status": "ok",
            "method": "abductio",
            "oracle_eval_eligible": True,
            "top1_match": not is_baseline,
            "top1_ambiguous": False,
            "top_root_id": "H_UND" if is_baseline else "R1",
            "brier": 0.40 if is_baseline else 0.20,
            "log_loss": 1.00 if is_baseline else 0.40,
        }
        report = {"rows": [row]}
        out_path = corpus / "results" / "backtest" / f"{ablation_label}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return out_path

    monkeypatch.setattr(backtest, "run_historical_backtest", fake_run_historical_backtest)

    report_path = backtest.run_historical_ablation_suite(
        case_ids=["case_a"],
        holdout_year=2025,
        run_dev=False,
        selected_only=True,
        credits=10,
        model="gpt-4.1-mini",
        temperature=0.0,
        timeout_s=30.0,
    )
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    variants = report.get("variants", [])
    assert [row.get("variant_id") for row in variants] == [
        "baseline",
        "pair_engine",
        "dynamic_und",
        "composition",
    ]
    assert variants[0].get("delta_top1_accuracy") == 0.0
    assert variants[1].get("delta_top1_accuracy") == 1.0
    assert variants[1].get("delta_mean_brier") == -0.2
    assert len(calls) == 4
    assert all(call["policy_override_type"] == "dict" for call in calls)
