from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from . import __version__
from .backtest import run_historical_ablation_suite, run_historical_backtest
from .config import corpus_root, inbox_root, spec_root
from .download import download_case_pdf, select_case_ids
from .evidence import build_evidence_packet
from .extract import ensure_extracts
from .hashutil import sha256_file, write_hashes
from .oracle import build_oracle
from .provenance import collect_provenance, git_head
from .registry import Registry, inbox_index, load_inbox
from .roots import build_roots_yaml
from .validate import validate_json_file


SPEC_FILES = [
    "type_spec.org",
    "leakage_checks.md",
    "oracle_strength_rubric.md",
    "metrics_spec.md",
    "roots_library.yaml",
    "roots_library.json",
]

def _spec_hashes(spec_dir: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for name in SPEC_FILES:
        path = spec_dir / name
        if path.exists():
            hashes[name] = sha256_file(path)
    schema_dir = spec_dir / "schemas"
    if schema_dir.exists():
        for path in sorted(schema_dir.glob("*.json")):
            hashes[f"schemas/{path.name}"] = sha256_file(path)
    return hashes


def _case_paths(case_id: str) -> Dict[str, Path]:
    base = corpus_root() / "cases" / case_id
    return {
        "base": base,
        "evidence_md": base / "evidence_packet.md",
        "evidence_json": base / "evidence_packet.json",
        "roots": base / "roots.yaml",
        "oracle": base / "oracle.md",
        "answer": base / "answer_key.md",
        "hashes": base / "hashes.txt",
        "manifest": base / "build_manifest.json",
    }


def _extracts_dir(case_id: str) -> Path:
    return corpus_root() / "extracts" / case_id


def ingest() -> None:
    corpus = corpus_root()
    registry = Registry.load(corpus / "index.csv")
    inbox_csv = inbox_root() / "inbox.csv"
    inbox_rows = load_inbox(inbox_csv)
    inbox_lookup = inbox_index(inbox_rows)

    for pdf_path in sorted(inbox_root().glob("*.pdf")):
        meta = inbox_lookup.get(pdf_path.name)
        if not meta:
            continue
        case_id = meta.get("case_id")
        if not case_id:
            continue
        sha = sha256_file(pdf_path)
        dest_path = corpus / pdf_path.name
        if not dest_path.exists():
            shutil.copy2(pdf_path, dest_path)

        row = registry.find(case_id) or {}
        row.update(meta)
        row["case_id"] = case_id
        row["pdf_filename"] = pdf_path.name
        row["sha256_pdf"] = sha
        row.setdefault("processing_status", "raw")
        registry.upsert(row)

    if registry.headers:
        registry.save()


def build_case(case_id: str) -> None:
    corpus = corpus_root()
    registry = Registry.load(corpus / "index.csv")
    row = registry.find(case_id)
    if not row:
        raise ValueError(f"Unknown case_id: {case_id}")

    pdf_name = row.get("pdf_filename") or f"{case_id}.pdf"
    pdf_path = corpus / pdf_name
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF: {pdf_path}")
    row["pdf_path"] = str(pdf_path)

    extracts_dir = _extracts_dir(case_id)
    ensure_extracts(pdf_path, extracts_dir)

    paths = _case_paths(case_id)
    evidence_md_path, evidence_json_path, leakage_warnings = build_evidence_packet(
        row, extracts_dir, spec_root(), paths["base"]
    )
    roots_path = build_roots_yaml(row, spec_root(), paths["base"])
    root_ids = _read_root_ids(roots_path)
    oracle_path, answer_path = build_oracle(row, extracts_dir, paths["base"], root_ids)

    hashes = {
        "pdf_sha256": sha256_file(pdf_path),
        "evidence_packet_md_sha256": sha256_file(evidence_md_path),
        "evidence_packet_json_sha256": sha256_file(evidence_json_path),
        "roots_yaml_sha256": sha256_file(roots_path),
        "oracle_md_sha256": sha256_file(oracle_path),
        "answer_key_md_sha256": sha256_file(answer_path),
    }
    write_hashes(paths["hashes"], hashes)

    manifest = {
        "case_id": case_id,
        "builder_version": __version__,
        "git_sha": git_head(),
        "pdf_sha256": hashes["pdf_sha256"],
        "spec_hashes": _spec_hashes(spec_root()),
        "leakage_warnings": leakage_warnings,
        "outputs": {
            "evidence_packet_md": str(evidence_md_path),
            "evidence_packet_json": str(evidence_json_path),
            "roots_yaml": str(roots_path),
            "oracle_md": str(oracle_path),
            "answer_key_md": str(answer_path),
        },
    }
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    row["processing_status"] = "built"
    row["evidence_packet_path"] = str(evidence_md_path)
    row["answer_key_path"] = str(answer_path)
    registry.upsert(row)
    registry.save()


def download_case(case_id: str, *, force: bool = False, timeout_s: float = 30.0) -> Dict[str, str]:
    corpus = corpus_root()
    registry = Registry.load(corpus / "index.csv")
    row = registry.find(case_id)
    if not row:
        raise ValueError(f"Unknown case_id: {case_id}")

    result = download_case_pdf(row, corpus, force=force, timeout_s=timeout_s)
    row["pdf_filename"] = result.pdf_path.name
    row["pdf_path"] = str(result.pdf_path)
    row["source_pdf_url"] = result.pdf_url
    row["sha256_pdf"] = result.sha256
    row.setdefault("processing_status", "raw")
    registry.upsert(row)
    registry.save()
    return row


def _read_root_ids(path: Path) -> List[str]:
    if not path.exists():
        return []
    root_ids: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- id:"):
            root_ids.append(line.split(":", 1)[1].strip())
    return root_ids


def _read_answer_key_root(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- oracle_root_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def _read_oracle_root(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- mapped_root_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def validate_case(case_id: str) -> None:
    paths = _case_paths(case_id)
    spec_dir = spec_root()
    validate_json_file(paths["evidence_json"], spec_dir / "schemas" / "evidence_packet.schema.json")
    root_ids = _read_root_ids(paths["roots"])
    if not root_ids:
        raise ValueError("roots.yaml has no root ids")
    answer_root = _read_answer_key_root(paths["answer"])
    oracle_root = _read_oracle_root(paths["oracle"])
    if answer_root and answer_root not in root_ids:
        raise ValueError(f"answer_key oracle_root_id not in roots: {answer_root}")
    if oracle_root and oracle_root not in root_ids:
        raise ValueError(f"oracle mapped_root_id not in roots: {oracle_root}")


def build_all(case_ids: Iterable[str]) -> None:
    for case_id in case_ids:
        build_case(case_id)


def validate_all(case_ids: Iterable[str]) -> None:
    for case_id in case_ids:
        validate_case(case_id)


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _results_dir() -> Path:
    path = corpus_root() / "results" / "pipeline"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _summarize_run(case_id: str, run_dir: Path) -> Dict[str, object]:
    result_path = run_dir / "result.json"
    data = json.loads(result_path.read_text(encoding="utf-8"))
    ledger = data.get("ledger", {})
    if not isinstance(ledger, dict):
        ledger = {}
    best_p = None
    winners: List[str] = []
    for root_id, p_value in ledger.items():
        try:
            score = float(p_value)
        except (TypeError, ValueError):
            continue
        rid = str(root_id)
        if best_p is None or score > best_p:
            best_p = score
            winners = [rid]
        elif abs(score - best_p) <= 1e-12:
            winners.append(rid)

    winners = sorted(winners)
    top1_ambiguous = len(winners) > 1
    top_root_id = winners[0] if len(winners) == 1 else ""
    top_root_p = float(best_p) if best_p is not None else 0.0

    answer_root = _read_answer_key_root(_case_paths(case_id)["answer"])
    return {
        "run_dir": str(run_dir),
        "top_root_id": top_root_id,
        "top_root_ids": list(winners),
        "top1_ambiguous": top1_ambiguous,
        "top_root_p": round(top_root_p, 8),
        "oracle_root_id": answer_root,
        "top1_match": bool(not top1_ambiguous and answer_root and top_root_id == answer_root),
        "oracle_in_top_tie": bool(top1_ambiguous and answer_root and answer_root in winners),
        "stop_reason": data.get("stop_reason"),
        "total_credits_spent": data.get("total_credits_spent"),
    }


def _count_true(rows: Iterable[Mapping[str, Any]], key: str) -> int:
    return sum(1 for row in rows if bool(row.get(key)))


def _write_pipeline_summary(
    markdown_path: Path,
    *,
    report_id: str,
    created_at_utc: str,
    rows: List[Dict[str, object]],
    settings: Mapping[str, object],
    provenance: Mapping[str, object],
) -> None:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    ran_rows = [row for row in ok_rows if bool(row.get("ran"))]
    top1_rows = [row for row in ran_rows if isinstance(row.get("top1_match"), bool)]
    top1_hits = sum(1 for row in top1_rows if bool(row.get("top1_match")))
    top1_rate = (top1_hits / len(top1_rows)) if top1_rows else None

    lines = [
        f"# AAIB Pipeline Summary ({report_id})",
        "",
        "## Provenance",
        f"- created_at_utc: `{created_at_utc}`",
        f"- aaib_bench_version: `{provenance.get('aaib_bench_version', '')}`",
        f"- repo_git_sha: `{provenance.get('repo_git_sha', '')}`",
        f"- repo_git_ref: `{provenance.get('repo_git_ref', '')}`",
        "",
        "## Settings",
        f"- do_download: `{settings.get('do_download')}`",
        f"- do_build: `{settings.get('do_build')}`",
        f"- do_validate: `{settings.get('do_validate')}`",
        f"- run_engine: `{settings.get('run_engine')}`",
        f"- run_credits: `{settings.get('run_credits')}`",
        f"- run_model: `{settings.get('run_model')}`",
        f"- run_temperature: `{settings.get('run_temperature')}`",
        f"- run_timeout_s: `{settings.get('run_timeout_s')}`",
        f"- strict_mece: `{settings.get('strict_mece')}`",
        f"- max_pair_overlap: `{settings.get('max_pair_overlap')}`",
        "",
        "## Aggregate Results",
        f"- total_cases: `{len(rows)}`",
        f"- ok_cases: `{len(ok_rows)}`",
        f"- error_cases: `{len(rows) - len(ok_rows)}`",
        f"- built_cases: `{_count_true(rows, 'built')}`",
        f"- validated_cases: `{_count_true(rows, 'validated')}`",
        f"- ran_cases: `{_count_true(rows, 'ran')}`",
        (
            f"- top1_match_rate_on_ran_cases: `{top1_rate:.4f}` ({top1_hits}/{len(top1_rows)})"
            if top1_rate is not None
            else "- top1_match_rate_on_ran_cases: `n/a`"
        ),
        "",
        "## Case Outcomes",
        "| case_id | status | built | validated | ran | top_root_id | oracle_root_id | top1_match | error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {case_id} | {status} | {built} | {validated} | {ran} | {top_root_id} | {oracle_root_id} | {top1_match} | {error} |".format(
                case_id=str(row.get("case_id", "")),
                status=str(row.get("status", "")),
                built=str(row.get("built", "")),
                validated=str(row.get("validated", "")),
                ran=str(row.get("ran", "")),
                top_root_id=str(row.get("top_root_id", "")),
                oracle_root_id=str(row.get("oracle_root_id", "")),
                top1_match=str(row.get("top1_match", "")),
                error=str(row.get("error", "")).replace("\n", " "),
            )
        )

    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_pipeline_report(
    rows: List[Dict[str, object]],
    *,
    settings: Mapping[str, object],
) -> Path:
    report_id = _now_stamp()
    base = _results_dir() / f"{report_id}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    markdown_path = base.with_suffix(".md")
    created_at_utc = datetime.now(timezone.utc).isoformat()
    provenance = collect_provenance()

    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    _write_pipeline_summary(
        markdown_path,
        report_id=report_id,
        created_at_utc=created_at_utc,
        rows=rows,
        settings=settings,
        provenance=provenance,
    )
    return json_path


def pipeline_cases(
    case_ids: Iterable[str],
    *,
    do_download: bool = True,
    do_build: bool = True,
    do_validate: bool = True,
    run_engine: bool = False,
    force_download: bool = False,
    timeout_s: float = 30.0,
    run_credits: int = 10,
    run_model: str = "gpt-4.1-mini",
    run_temperature: float = 0.0,
    run_timeout_s: float = 60.0,
    strict_mece: bool | None = None,
    max_pair_overlap: float | None = None,
    hardened_one_shot: bool = False,
) -> Path:
    rows: List[Dict[str, object]] = []
    for case_id in case_ids:
        row: Dict[str, object] = {"case_id": case_id, "status": "ok"}
        try:
            if do_download:
                download_case(case_id, force=force_download, timeout_s=timeout_s)
                row["downloaded"] = True
            if do_build:
                build_case(case_id)
                row["built"] = True
            if do_validate:
                validate_case(case_id)
                row["validated"] = True
            if run_engine:
                from .run import run_case

                run_dir = run_case(
                    case_id=case_id,
                    credits=run_credits,
                    model=run_model,
                    temperature=run_temperature,
                    timeout_s=run_timeout_s,
                    strict_mece=strict_mece,
                    max_pair_overlap=max_pair_overlap,
                    hardened_one_shot=bool(hardened_one_shot),
                )
                row["ran"] = True
                row.update(_summarize_run(case_id, run_dir))
        except Exception as exc:  # pragma: no cover - branch exercised by integration use
            row["status"] = "error"
            row["error"] = str(exc)
        rows.append(row)
    return _write_pipeline_report(
        rows,
        settings={
            "do_download": do_download,
            "do_build": do_build,
            "do_validate": do_validate,
            "run_engine": run_engine,
            "run_credits": run_credits,
            "run_model": run_model,
            "run_temperature": run_temperature,
            "run_timeout_s": run_timeout_s,
            "strict_mece": strict_mece,
            "max_pair_overlap": max_pair_overlap,
            "hardened_one_shot": bool(hardened_one_shot),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="aaib_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest")

    build_parser = sub.add_parser("build")
    build_parser.add_argument("--case", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--case")
    validate_parser.add_argument("--all", action="store_true")

    download_parser = sub.add_parser("download")
    download_target = download_parser.add_mutually_exclusive_group(required=True)
    download_target.add_argument("--case")
    download_target.add_argument("--all", action="store_true")
    download_target.add_argument("--selected", action="store_true")
    download_parser.add_argument("--force", action="store_true")
    download_parser.add_argument("--timeout", type=float, default=30.0)

    run_parser = sub.add_parser("run")
    run_target = run_parser.add_mutually_exclusive_group(required=True)
    run_target.add_argument("--case")
    run_target.add_argument("--all", action="store_true")
    run_target.add_argument("--selected", action="store_true")
    run_parser.add_argument("--credits", type=int, default=10)
    run_parser.add_argument("--model", default="gpt-4.1-mini")
    run_parser.add_argument("--temperature", type=float, default=0.0)
    run_parser.add_argument("--timeout-s", type=float, default=60.0)
    run_parser.add_argument("--max-pair-overlap", type=float, default=None)
    run_parser.add_argument("--hardened-one-shot", action="store_true")
    run_mece_mode = run_parser.add_mutually_exclusive_group()
    run_mece_mode.add_argument("--strict-mece", dest="strict_mece", action="store_true")
    run_mece_mode.add_argument("--no-strict-mece", dest="strict_mece", action="store_false")
    run_parser.set_defaults(strict_mece=None)

    pipeline_parser = sub.add_parser("pipeline")
    pipeline_target = pipeline_parser.add_mutually_exclusive_group(required=True)
    pipeline_target.add_argument("--case")
    pipeline_target.add_argument("--all", action="store_true")
    pipeline_target.add_argument("--selected", action="store_true")
    pipeline_parser.add_argument("--skip-download", action="store_true")
    pipeline_parser.add_argument("--skip-build", action="store_true")
    pipeline_parser.add_argument("--skip-validate", action="store_true")
    pipeline_parser.add_argument("--run", action="store_true")
    pipeline_parser.add_argument("--force-download", action="store_true")
    pipeline_parser.add_argument("--timeout", type=float, default=30.0)
    pipeline_parser.add_argument("--credits", type=int, default=10)
    pipeline_parser.add_argument("--model", default="gpt-4.1-mini")
    pipeline_parser.add_argument("--temperature", type=float, default=0.0)
    pipeline_parser.add_argument("--timeout-s", type=float, default=60.0)
    pipeline_parser.add_argument("--max-pair-overlap", type=float, default=None)
    pipeline_parser.add_argument("--hardened-one-shot", action="store_true")
    pipeline_mece_mode = pipeline_parser.add_mutually_exclusive_group()
    pipeline_mece_mode.add_argument("--strict-mece", dest="strict_mece", action="store_true")
    pipeline_mece_mode.add_argument("--no-strict-mece", dest="strict_mece", action="store_false")
    pipeline_parser.set_defaults(strict_mece=None)

    backtest_parser = sub.add_parser("historical-backtest")
    backtest_target = backtest_parser.add_mutually_exclusive_group(required=True)
    backtest_target.add_argument("--case")
    backtest_target.add_argument("--all", action="store_true")
    backtest_target.add_argument("--selected", action="store_true")
    backtest_parser.add_argument("--holdout-year", type=int)
    backtest_parser.add_argument("--run-dev", action="store_true")
    backtest_parser.add_argument("--include-unselected", action="store_true")
    backtest_parser.add_argument("--credits", type=int, default=10)
    backtest_parser.add_argument("--model", default="gpt-4.1-mini")
    backtest_parser.add_argument("--temperature", type=float, default=0.0)
    backtest_parser.add_argument("--timeout-s", type=float, default=60.0)
    backtest_parser.add_argument("--max-pair-overlap", type=float, default=None)
    backtest_parser.add_argument("--hardened-one-shot", action="store_true")
    backtest_parser.add_argument(
        "--locked-policy-profile",
        default=None,
        help="Named locked policy profile (e.g., boeing_inference_v1).",
    )
    backtest_mece_mode = backtest_parser.add_mutually_exclusive_group()
    backtest_mece_mode.add_argument("--strict-mece", dest="strict_mece", action="store_true")
    backtest_mece_mode.add_argument("--no-strict-mece", dest="strict_mece", action="store_false")
    backtest_parser.set_defaults(strict_mece=None)
    backtest_parser.add_argument(
        "--methods",
        default="abductio,logodds,checklist,prior",
        help="Comma-separated methods: abductio,logodds,checklist,prior",
    )

    ablation_parser = sub.add_parser("historical-ablation")
    ablation_target = ablation_parser.add_mutually_exclusive_group(required=True)
    ablation_target.add_argument("--case")
    ablation_target.add_argument("--all", action="store_true")
    ablation_target.add_argument("--selected", action="store_true")
    ablation_parser.add_argument("--holdout-year", type=int)
    ablation_parser.add_argument("--run-dev", action="store_true")
    ablation_parser.add_argument("--include-unselected", action="store_true")
    ablation_parser.add_argument("--credits", type=int, default=10)
    ablation_parser.add_argument("--model", default="gpt-4.1-mini")
    ablation_parser.add_argument("--temperature", type=float, default=0.0)
    ablation_parser.add_argument("--timeout-s", type=float, default=60.0)
    ablation_parser.add_argument("--max-pair-overlap", type=float, default=None)
    ablation_parser.add_argument(
        "--locked-policy-profile",
        default=None,
        help="Named locked policy profile (e.g., boeing_inference_v1).",
    )
    ablation_mece_mode = ablation_parser.add_mutually_exclusive_group()
    ablation_mece_mode.add_argument("--strict-mece", dest="strict_mece", action="store_true")
    ablation_mece_mode.add_argument("--no-strict-mece", dest="strict_mece", action="store_false")
    ablation_parser.set_defaults(strict_mece=None)

    args = parser.parse_args()

    if args.command == "ingest":
        ingest()
        return
    if args.command == "build":
        build_case(args.case)
        return
    if args.command == "validate":
        if args.all:
            corpus = corpus_root()
            registry = Registry.load(corpus / "index.csv")
            case_ids = [row.get("case_id", "") for row in registry.rows if row.get("case_id")]
            validate_all(case_ids)
            return
        if not args.case:
            raise SystemExit("--case is required unless --all is used")
        validate_case(args.case)
        return
    if args.command == "download":
        registry = Registry.load(corpus_root() / "index.csv")
        case_ids = select_case_ids(
            registry.rows,
            case_id=args.case,
            use_all=bool(args.all),
            use_selected=bool(args.selected),
        )
        for case_id in case_ids:
            row = download_case(case_id, force=bool(args.force), timeout_s=float(args.timeout))
            print(f"downloaded {case_id}: {row.get('pdf_filename', '')}")
        return
    if args.command == "run":
        registry = Registry.load(corpus_root() / "index.csv")
        case_ids = select_case_ids(
            registry.rows,
            case_id=args.case,
            use_all=bool(args.all),
            use_selected=bool(args.selected),
        )
        from .run import run_case

        for case_id in case_ids:
            run_dir = run_case(
                case_id=case_id,
                credits=int(args.credits),
                model=str(args.model),
                temperature=float(args.temperature),
                timeout_s=float(args.timeout_s),
                strict_mece=args.strict_mece,
                max_pair_overlap=args.max_pair_overlap,
                hardened_one_shot=bool(args.hardened_one_shot),
            )
            print(f"ran {case_id}: {run_dir}")
        return
    if args.command == "pipeline":
        registry = Registry.load(corpus_root() / "index.csv")
        case_ids = select_case_ids(
            registry.rows,
            case_id=args.case,
            use_all=bool(args.all),
            use_selected=bool(args.selected),
        )
        report_path = pipeline_cases(
            case_ids,
            do_download=not bool(args.skip_download),
            do_build=not bool(args.skip_build),
            do_validate=not bool(args.skip_validate),
            run_engine=bool(args.run),
            force_download=bool(args.force_download),
            timeout_s=float(args.timeout),
            run_credits=int(args.credits),
            run_model=str(args.model),
            run_temperature=float(args.temperature),
            run_timeout_s=float(args.timeout_s),
            strict_mece=args.strict_mece,
            max_pair_overlap=args.max_pair_overlap,
            hardened_one_shot=bool(args.hardened_one_shot),
        )
        print(f"pipeline report: {report_path}")
        return
    if args.command == "historical-backtest":
        registry = Registry.load(corpus_root() / "index.csv")
        case_ids = select_case_ids(
            registry.rows,
            case_id=args.case,
            use_all=bool(args.all),
            use_selected=bool(args.selected),
        )
        report_path = run_historical_backtest(
            case_ids=case_ids,
            holdout_year=args.holdout_year,
            run_dev=bool(args.run_dev),
            selected_only=not bool(args.include_unselected),
            credits=int(args.credits),
            model=str(args.model),
            temperature=float(args.temperature),
            timeout_s=float(args.timeout_s),
            strict_mece=args.strict_mece,
            max_pair_overlap=args.max_pair_overlap,
            hardened_one_shot=bool(args.hardened_one_shot),
            locked_policy_profile=(
                args.locked_policy_profile.strip()
                if isinstance(args.locked_policy_profile, str) and args.locked_policy_profile.strip()
                else None
            ),
            methods=[str(args.methods)],
        )
        print(f"historical backtest report: {report_path}")
        return
    if args.command == "historical-ablation":
        registry = Registry.load(corpus_root() / "index.csv")
        case_ids = select_case_ids(
            registry.rows,
            case_id=args.case,
            use_all=bool(args.all),
            use_selected=bool(args.selected),
        )
        report_path = run_historical_ablation_suite(
            case_ids=case_ids,
            holdout_year=args.holdout_year,
            run_dev=bool(args.run_dev),
            selected_only=not bool(args.include_unselected),
            credits=int(args.credits),
            model=str(args.model),
            temperature=float(args.temperature),
            timeout_s=float(args.timeout_s),
            strict_mece=args.strict_mece,
            max_pair_overlap=args.max_pair_overlap,
            locked_policy_profile=(
                args.locked_policy_profile.strip()
                if isinstance(args.locked_policy_profile, str) and args.locked_policy_profile.strip()
                else None
            ),
        )
        print(f"historical ablation report: {report_path}")
        return


if __name__ == "__main__":
    main()
