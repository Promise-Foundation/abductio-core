from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def _load_required(schema_path: Path) -> List[str]:
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return list(schema.get("required", []))


def validate_required(data: Dict[str, object], required: List[str]) -> None:
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


def validate_json_file(json_path: Path, schema_path: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    required = _load_required(schema_path)
    validate_required(data, required)
