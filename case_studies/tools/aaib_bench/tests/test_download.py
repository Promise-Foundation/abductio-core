from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from case_studies.tools.aaib_bench.aaib_bench import cli
from case_studies.tools.aaib_bench.aaib_bench.download import download_case_pdf, select_case_ids
from case_studies.tools.aaib_bench.aaib_bench.hashutil import sha256_file


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _write_index(path: Path, rows: list[dict[str, str]]) -> None:
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_download_case_pdf_from_direct_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    row = {
        "case_id": "sample_case",
        "pdf_filename": "sample_case.pdf",
        "source_url": "https://example.test/sample_case.pdf",
    }
    pdf_bytes = b"%PDF-1.7\nsample\n"

    def fake_urlopen(request, timeout=30.0):  # noqa: ANN001
        url = request.full_url if hasattr(request, "full_url") else str(request)
        assert url == "https://example.test/sample_case.pdf"
        return _FakeResponse(pdf_bytes)

    monkeypatch.setattr("case_studies.tools.aaib_bench.aaib_bench.download.urlopen", fake_urlopen)

    result = download_case_pdf(row, tmp_path)
    assert result.downloaded is True
    assert result.pdf_path.exists()
    assert result.sha256 == sha256_file(result.pdf_path)

    second = download_case_pdf(row, tmp_path)
    assert second.downloaded is False
    assert second.sha256 == result.sha256


def test_download_case_pdf_resolves_from_search_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row = {
        "case_id": "Boeing_737-8AS_9H-QAA_12-25",
        "pdf_filename": "Boeing_737-8AS_9H-QAA_12-25.pdf",
        "source_url": "https://www.gov.uk/aaib-reports",
        "source_doc_id": "AAIB-30304",
        "doc_title": "Boeing 737-8AS 9H-QAA 12-25",
        "aircraft_type": "Boeing 737-8AS",
        "registration": "9H-QAA",
    }
    search_payload = {
        "results": [{"link": "/aaib-reports/aaib-investigation-to-boeing-737-8as-9h-qaa"}]
    }
    page_html = """
    <html>
      <body>
        <a href="/government/uploads/system/uploads/attachment_data/file/000/AAIB_Bulletin_12-2025.pdf">Download bulletin</a>
        <a href="/government/uploads/system/uploads/attachment_data/file/111/Boeing_737-8AS_9H-QAA_12-25.pdf">Download report</a>
      </body>
    </html>
    """
    pdf_bytes = b"%PDF-1.4\nreport\n"

    def fake_urlopen(request, timeout=30.0):  # noqa: ANN001
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "api/search.json" in url:
            return _FakeResponse(json.dumps(search_payload).encode("utf-8"))
        if url == "https://www.gov.uk/aaib-reports":
            return _FakeResponse(b"<html><body>listing</body></html>")
        if "aaib-investigation-to-boeing-737-8as-9h-qaa" in url:
            return _FakeResponse(page_html.encode("utf-8"))
        if "Boeing_737-8AS_9H-QAA_12-25.pdf" in url:
            return _FakeResponse(pdf_bytes)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("case_studies.tools.aaib_bench.aaib_bench.download.urlopen", fake_urlopen)
    result = download_case_pdf(row, tmp_path)
    assert result.pdf_url.endswith("Boeing_737-8AS_9H-QAA_12-25.pdf")
    assert result.pdf_path.name == "Boeing_737-8AS_9H-QAA_12-25.pdf"


def test_select_case_ids_modes() -> None:
    rows = [
        {"case_id": "A", "selected_for_corpus": "Y"},
        {"case_id": "B", "selected_for_corpus": "N"},
    ]
    assert select_case_ids(rows, case_id="A") == ["A"]
    assert select_case_ids(rows, use_all=True) == ["A", "B"]
    assert select_case_ids(rows, use_selected=True) == ["A"]


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    (root / "extracts" / "sample_case").mkdir(parents=True)
    (root / "cases" / "sample_case").mkdir(parents=True)
    (root / "spec" / "schemas").mkdir(parents=True)
    monkeypatch.setenv("AAIB_CORPUS_ROOT", str(root))

    (root / "spec" / "leakage_checks.md").write_text("- concluded\n", encoding="utf-8")
    (root / "spec" / "roots_library.json").write_text(
        '{"root_sets": {"AAIB_GROUND_COLLISION_S1_v1": {"roots": [{"id": "R1"}, {"id": "H_OTHER"}]}}}\n',
        encoding="utf-8",
    )
    (root / "spec" / "roots_library.yaml").write_text("root_sets: {}\n", encoding="utf-8")
    (root / "spec" / "oracle_strength_rubric.md").write_text("# rubric\n", encoding="utf-8")
    (root / "spec" / "metrics_spec.md").write_text("# metrics\n", encoding="utf-8")
    (root / "spec" / "type_spec.org").write_text("* type\n", encoding="utf-8")
    (root / "spec" / "schemas" / "evidence_packet.schema.json").write_text(
        '{"required": ["case_id", "evidence_freeze_time_utc", "pdf_sha256", "items"]}\n',
        encoding="utf-8",
    )
    (root / "sample.pdf").write_bytes(b"%PDF-1.7\nsample\n")
    extracts = root / "extracts" / "sample_case"
    (extracts / "history.txt").write_text("History line", encoding="utf-8")
    (extracts / "synopsis.txt").write_text("Synopsis line", encoding="utf-8")
    (extracts / "analysis.txt").write_text("Analysis line", encoding="utf-8")
    (extracts / "conclusion.txt").write_text("Conclusion line", encoding="utf-8")
    (extracts / "safety_actions.txt").write_text("Safety action", encoding="utf-8")

    _write_index(
        root / "index.csv",
        [
            {
                "case_id": "sample_case",
                "pdf_filename": "sample.pdf",
                "sha256_pdf": sha256_file(root / "sample.pdf"),
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
    return root


def test_pipeline_writes_report(corpus: Path) -> None:
    report_path = cli.pipeline_cases(
        ["sample_case"],
        do_download=False,
        do_build=True,
        do_validate=True,
        run_engine=False,
    )
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report[0]["status"] == "ok"
    assert report[0]["built"] is True
    assert report[0]["validated"] is True
    summary_path = report_path.with_suffix(".md")
    assert summary_path.exists()
    summary = summary_path.read_text(encoding="utf-8")
    assert "AAIB Pipeline Summary" in summary
    assert "aaib_bench_version" in summary
