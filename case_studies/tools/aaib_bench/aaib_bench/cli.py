from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List

from . import __version__
from .config import corpus_root, inbox_root, spec_root
from .evidence import build_evidence_packet
from .extract import ensure_extracts
from .hashutil import sha256_file, write_hashes
from .normalize import normalize_text
from .oracle import build_oracle
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


def _git_head() -> str:
    git_dir = Path(".git")
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return ""
    head = head_path.read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        ref = head.split(" ", 1)[1]
        ref_path = git_dir / ref
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8").strip()
    return head


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
        "git_sha": _git_head(),
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="aaib_bench")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest")

    build_parser = sub.add_parser("build")
    build_parser.add_argument("--case", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--case")
    validate_parser.add_argument("--all", action="store_true")

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


if __name__ == "__main__":
    main()
