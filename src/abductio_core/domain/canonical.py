from __future__ import annotations

import hashlib


def normalize_statement(text: str) -> str:
    return " ".join(text.strip().lower().split())


def canonical_id_for_statement(text: str) -> str:
    normalized = normalize_statement(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
