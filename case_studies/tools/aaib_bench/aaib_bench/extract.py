from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from .hashutil import sha256_file
from .normalize import normalize_text

REQUIRED_SECTIONS = ["history", "synopsis", "analysis", "conclusion", "safety_actions"]


def extract_manifest(pdf_path: Path, extracts_dir: Path) -> Dict[str, object]:
    sections = {}
    for name in REQUIRED_SECTIONS:
        path = extracts_dir / f"{name}.txt"
        if not path.exists():
            continue
        content = normalize_text(path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        sections[name] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    return {
        "pdf_sha256": sha256_file(pdf_path),
        "extracts": sections,
        "extractor_version": "stub-v1",
    }


def ensure_extracts(pdf_path: Path, extracts_dir: Path) -> Path:
    extracts_dir.mkdir(parents=True, exist_ok=True)
    missing = [name for name in REQUIRED_SECTIONS if not (extracts_dir / f"{name}.txt").exists()]
    if missing:
        raise FileNotFoundError(f"Missing extracted sections: {missing}")
    manifest = extract_manifest(pdf_path, extracts_dir)
    manifest_path = extracts_dir / "extract_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path
