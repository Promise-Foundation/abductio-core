from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from . import __version__


def _resolve_git_dir(path: Path) -> Path:
    if path.is_dir():
        return path
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("gitdir:"):
        return path
    target = text.split(":", 1)[1].strip()
    target_path = Path(target)
    if target_path.is_absolute():
        return target_path
    return (path.parent / target_path).resolve()


def _find_git_dir(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        marker = candidate / ".git"
        if marker.exists():
            return _resolve_git_dir(marker)
    return None


def git_head(start: Path | None = None) -> str:
    base = start or Path.cwd()
    git_dir = _find_git_dir(base.resolve())
    if git_dir is None:
        return ""
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


def git_ref(start: Path | None = None) -> str:
    base = start or Path.cwd()
    git_dir = _find_git_dir(base.resolve())
    if git_dir is None:
        return ""
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return ""
    head = head_path.read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        return head.split(" ", 1)[1]
    return ""


def collect_provenance(start: Path | None = None) -> Dict[str, Any]:
    return {
        "aaib_bench_version": __version__,
        "repo_git_sha": git_head(start=start),
        "repo_git_ref": git_ref(start=start),
    }
