from __future__ import annotations

import csv
from pathlib import Path

import pytest

from case_studies.tools.aaib_bench.aaib_bench import cli
from case_studies.tools.aaib_bench.aaib_bench.hashutil import sha256_file


def _write_index(path: Path, rows: list[dict[str, str]]) -> None:
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_inbox(path: Path, rows: list[dict[str, str]]) -> None:
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    (root / "inbox").mkdir(parents=True)
    (root / "extracts" / "sample_case").mkdir(parents=True)
    (root / "cases" / "sample_case").mkdir(parents=True)
    (root / "spec" / "schemas").mkdir(parents=True)
    monkeypatch.setenv("AAIB_CORPUS_ROOT", str(root))

    (root / "spec" / "leakage_checks.md").write_text("- concluded\n", encoding="utf-8")
    (root / "spec" / "roots_library.json").write_text(
        '{"root_sets": {"AAIB_GROUND_COLLISION_S1_v1": {"roots": [{"id": "R1"}, {"id": "H_OTHER"}]}}}\n',
        encoding="utf-8",
    )
    (root / "spec" / "schemas" / "evidence_packet.schema.json").write_text(
        '{"required": ["case_id", "evidence_freeze_time_utc", "pdf_sha256", "items"]}\n',
        encoding="utf-8",
    )

    return root


def test_ingest_updates_registry(corpus: Path) -> None:
    pdf_path = corpus / "inbox" / "sample.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    _write_inbox(
        corpus / "inbox" / "inbox.csv",
        [{"pdf_filename": "sample.pdf", "case_id": "sample_case"}],
    )
    _write_index(corpus / "index.csv", [])

    cli.ingest()

    rows = list(csv.DictReader((corpus / "index.csv").open(encoding="utf-8")))
    assert rows
    assert rows[0]["case_id"] == "sample_case"
    assert rows[0]["sha256_pdf"] == sha256_file(pdf_path)


def test_build_generates_outputs(corpus: Path) -> None:
    pdf_path = corpus / "sample.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "sample_case",
                "pdf_filename": "sample.pdf",
                "sha256_pdf": sha256_file(pdf_path),
                "source_family": "aaib_uk",
                "source_agency": "AAIB",
                "source_doc_id": "DOC",
                "bulletin_issue": "01/2026",
                "retrieved_date_utc": "2026-01-08",
                "root_set_id": "AAIB_GROUND_COLLISION_S1_v1",
                "label_root_id": "R1",
                "reference_strength": "OS-3",
                "reference_type": "conclusion",
                "processing_status": "raw",
            }
        ],
    )
    extracts = corpus / "extracts" / "sample_case"
    (extracts / "history.txt").write_text("History line", encoding="utf-8")
    (extracts / "synopsis.txt").write_text("Synopsis line", encoding="utf-8")
    (extracts / "analysis.txt").write_text("Analysis line", encoding="utf-8")
    (extracts / "conclusion.txt").write_text("Conclusion line", encoding="utf-8")
    (extracts / "safety_actions.txt").write_text("Safety action", encoding="utf-8")

    cli.build_case("sample_case")

    evidence = (corpus / "cases" / "sample_case" / "evidence_packet.md").read_text(encoding="utf-8")
    assert "Analysis line" not in evidence
    assert "Conclusion line" not in evidence

    assert (corpus / "cases" / "sample_case" / "roots.yaml").exists()
    assert (corpus / "cases" / "sample_case" / "oracle.md").exists()
    assert (corpus / "cases" / "sample_case" / "answer_key.md").exists()


def test_validate_case(corpus: Path) -> None:
    pdf_path = corpus / "sample.pdf"
    pdf_path.write_text("pdf", encoding="utf-8")
    _write_index(
        corpus / "index.csv",
        [
            {
                "case_id": "sample_case",
                "pdf_filename": "sample.pdf",
                "sha256_pdf": sha256_file(pdf_path),
                "source_family": "aaib_uk",
                "source_agency": "AAIB",
                "source_doc_id": "DOC",
                "bulletin_issue": "01/2026",
                "retrieved_date_utc": "2026-01-08",
                "root_set_id": "AAIB_GROUND_COLLISION_S1_v1",
                "label_root_id": "R1",
                "reference_strength": "OS-3",
                "reference_type": "conclusion",
                "processing_status": "raw",
            }
        ],
    )
    extracts = corpus / "extracts" / "sample_case"
    (extracts / "history.txt").write_text("History line", encoding="utf-8")
    (extracts / "synopsis.txt").write_text("Synopsis line", encoding="utf-8")
    (extracts / "analysis.txt").write_text("Analysis line", encoding="utf-8")
    (extracts / "conclusion.txt").write_text("Conclusion line", encoding="utf-8")
    (extracts / "safety_actions.txt").write_text("Safety action", encoding="utf-8")

    cli.build_case("sample_case")
    cli.validate_case("sample_case")
