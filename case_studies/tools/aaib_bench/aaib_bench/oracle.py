from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple

from .normalize import normalize_text


def _first_nonempty(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return text.splitlines()[0].strip()


def build_oracle(
    case_row: Dict[str, str], extracts_dir: Path, output_dir: Path, valid_root_ids: Iterable[str]
) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_id = case_row.get("case_id", "")
    reference_statement = case_row.get("reference_statement", "").strip()
    conclusion = _first_nonempty(extracts_dir / "conclusion.txt")
    synopsis = _first_nonempty(extracts_dir / "synopsis.txt")
    oracle_excerpt = reference_statement or conclusion or synopsis or ""

    mapped_root = case_row.get("label_root_id", "")
    valid_set = {root_id for root_id in valid_root_ids if root_id}
    if mapped_root not in valid_set:
        raise ValueError(f"mapped_root_id must be one of {sorted(valid_set)}")
    raw_strength = case_row.get("reference_strength", "").strip()
    os_class = raw_strength or "OS-3"
    if not os_class.startswith("OS-"):
        letter_map = {"A": "OS-3", "B": "OS-2", "C": "OS-1"}
        if os_class in letter_map:
            os_class = letter_map[os_class]
        else:
            raise ValueError(f"Unsupported reference_strength: {raw_strength}")
    if os_class not in {"OS-1", "OS-2", "OS-3", "OS-4", "OS-5"}:
        raise ValueError(f"Invalid OS class: {os_class}")

    oracle_md_lines = [
        f"# Oracle — {case_id}",
        "",
        "## Oracle source",
        f"- oracle_type: {case_row.get('reference_type', 'conclusion')}",
        f"- doc_id: {case_row.get('source_doc_id', '')}",
        f"- retrieval_date_utc: {case_row.get('retrieved_date_utc', '')}",
        "",
        "## Oracle excerpt",
        oracle_excerpt or "(missing)",
        "",
        "## Mapping to root set",
        f"- mapped_root_id: {mapped_root}",
        f"- OS_class: {os_class}",
    ]
    oracle_md = normalize_text("\n".join(oracle_md_lines))
    oracle_md_path = output_dir / "oracle.md"
    oracle_md_path.write_text(oracle_md, encoding="utf-8")

    label_confidence = case_row.get("label_confidence_hint", "") or "medium"
    answer_md_lines = [
        f"# Answer key (oracle label) — {case_id}",
        "",
        "## Label",
        f"- oracle_root_id: {mapped_root}",
        f"- label_confidence_hint: {label_confidence}",
        "",
        "## Oracle strength",
        f"- OS_class: {os_class}",
    ]
    answer_md = normalize_text("\n".join(answer_md_lines))
    answer_md_path = output_dir / "answer_key.md"
    answer_md_path.write_text(answer_md, encoding="utf-8")

    return oracle_md_path, answer_md_path
