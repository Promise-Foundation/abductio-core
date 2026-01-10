from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_hashes(path: Path, entries: Dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in sorted(entries.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def hash_files(paths: Iterable[Path]) -> Dict[str, str]:
    return {path.name: sha256_file(path) for path in paths}
