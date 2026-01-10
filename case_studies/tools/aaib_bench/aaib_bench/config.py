from __future__ import annotations

import os
from pathlib import Path


def corpus_root() -> Path:
    return Path(os.getenv("AAIB_CORPUS_ROOT", "case_studies/data/UK_AAIB_Reports"))


def spec_root() -> Path:
    return corpus_root() / "spec"


def inbox_root() -> Path:
    return corpus_root() / "inbox"
