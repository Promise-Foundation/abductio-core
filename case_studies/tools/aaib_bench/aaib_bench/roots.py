from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .normalize import normalize_text


def _load_roots_library(spec_dir: Path) -> Dict[str, object]:
    json_path = spec_dir / "roots_library.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))
    raise FileNotFoundError("roots_library.json is required for builds")


def build_roots_yaml(case_row: Dict[str, str], spec_dir: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    library = _load_roots_library(spec_dir)
    root_set_id = case_row.get("root_set_id") or "AAIB_GROUND_COLLISION_S1_v1"
    root_set = library.get("root_sets", {}).get(root_set_id)
    if not isinstance(root_set, dict):
        raise ValueError(f"Unknown root_set_id: {root_set_id}")

    open_world = case_row.get("open_world_mode") or "Y"
    open_world_mode = "true" if str(open_world).strip().upper() in {"Y", "TRUE", "1"} else "false"

    lines: List[str] = [
        f"case_id: {case_row.get('case_id', '')}",
        f"scope: {case_row.get('benchmark_scope_id', 'S1')}",
        f"root_set_id: {root_set_id}",
        "",
        f"open_world_mode: {open_world_mode}",
        "roots:",
    ]

    for root in root_set.get("roots", []):
        root_id = root.get("id")
        if not root_id:
            continue
        lines.append(f"  - id: {root_id}")
        nec_slots = root.get("nec_slots", [])
        if nec_slots:
            lines.append("    nec_slots:")
            for slot in nec_slots:
                slot_id = slot.get("id") if isinstance(slot, dict) else str(slot)
                if slot_id:
                    lines.append(f"      - {slot_id}")

    roots_path = output_dir / "roots.yaml"
    roots_path.write_text(normalize_text("\n".join(lines)), encoding="utf-8")
    return roots_path
