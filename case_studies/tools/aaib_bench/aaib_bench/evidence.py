from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .hashutil import sha256_file
from .normalize import normalize_text

ALLOWED_SECTIONS = ["history", "synopsis"]
DISALLOWED_SECTIONS = ["analysis", "conclusion", "safety_actions"]
DROP_PREFIXES = (
    "Figure",
    "Footnote",
    "AAIB Bulletin",
    "All times are UTC",
    "Human performance",
    "Situation awareness",
    "Startle and surprise",
    "Aircraft marshalling signals",
    "Ground handling agent’s comments",
)
DROP_SUBSTRINGS = (
    "©",
    "Crown copyright",
    "Figure",
    "report discusses",
    "safety action",
    "safety actions",
    "since this accident",
    "since the accident",
    "Upgraded TRP",
    "Footnote",
    "Location of relevant stands",
    "training modules",
    "Aviate",
    "navigate",
    "communicate",
    "Startle",
    "Surprise",
    "EASA",
    "Just Culture",
    "With hindsight",
)
LEAKAGE_KEYWORDS = (
    "concluded",
    "cause",
    "caused",
    "probable",
    "resulted from",
    "therefore",
    "led to",
    "root cause",
    "the investigation found",
)


def _load_section(path: Path) -> str:
    return normalize_text(path.read_text(encoding="utf-8"))


def _split_lines(text: str) -> List[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def _merge_lines(lines: List[str]) -> List[str]:
    merged: List[str] = []
    buffer = ""
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if not buffer:
            buffer = line
        else:
            buffer = f"{buffer} {line}"
        if re.search(r"[.!?]\"?$", line):
            merged.append(buffer.strip())
            buffer = ""
    if buffer:
        merged.append(buffer.strip())
    return merged


def _sanitize_line(line: str) -> str:
    line = re.sub(r"\(Figure[^)]*\)", "", line)
    line = re.sub(r"\bFigure\s+\d+\b", "", line)
    line = re.sub(r"(?<=\w)\s\d{1,2}(?=\s*\()", "", line)
    line = re.sub(r"[’']\s*\d{1,2}(?=\s*\()", "’", line)
    line = re.sub(r"\bsuch that the tug was meant to stop\b", "", line, flags=re.IGNORECASE)
    line = re.sub(r"\bRealising what had happened,\s*", "", line, flags=re.IGNORECASE)
    line = re.sub(r"\s*,\s*\.", ".", line)
    line = re.sub(r"\s+\.", ".", line)
    line = re.sub(r"\s+,", ",", line)
    line = re.sub(r"\s{2,}", " ", line)
    return line.strip()


def _clean_lines(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        line = _sanitize_line(re.sub(r"\s+", " ", line).strip())
        if not line:
            continue
        if re.fullmatch(r"\d+", line) or re.fullmatch(r"\d+\s+\w.*", line):
            continue
        if any(line.startswith(prefix) for prefix in DROP_PREFIXES):
            continue
        if any(substr.lower() in line.lower() for substr in DROP_SUBSTRINGS):
            continue
        if any(keyword.lower() in line.lower() for keyword in LEAKAGE_KEYWORDS):
            continue
        if line and line[0].islower():
            line = line[0].upper() + line[1:]
        cleaned.append(line)
    return cleaned


def _load_keywords(spec_path: Path) -> List[str]:
    if not spec_path.exists():
        return []
    keywords: List[str] = []
    for line in spec_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-"):
            keywords.append(line.lstrip("- "))
    return [k for k in keywords if k]


def build_evidence_packet(
    case_row: Dict[str, str], extracts_dir: Path, spec_dir: Path, output_dir: Path
) -> Tuple[Path, Path, List[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(case_row.get("pdf_path", ""))
    pdf_sha = case_row.get("sha256_pdf") or (sha256_file(pdf_path) if pdf_path.exists() else "")

    items: List[Dict[str, str]] = []
    for section in ALLOWED_SECTIONS:
        section_path = extracts_dir / f"{section}.txt"
        if not section_path.exists():
            continue
        raw_lines = _split_lines(_load_section(section_path))
        merged = _merge_lines(raw_lines)
        cleaned = _clean_lines(merged)
        for idx, line in enumerate(cleaned, start=1):
            item_id = f"{section[:1].upper()}{idx}"
            items.append({"id": item_id, "text": line, "source": section})

    packet = {
        "case_id": case_row.get("case_id", ""),
        "evidence_freeze_time_utc": case_row.get("retrieved_date_utc", ""),
        "pdf_sha256": pdf_sha,
        "items": items,
    }

    evidence_md_lines = [
        f"# Evidence Packet (E_T) — {case_row.get('case_id', '')}",
        "",
        "## Provenance",
        f"- source_family: {case_row.get('source_family', '')}",
        f"- source_agency: {case_row.get('source_agency', '')}",
        f"- doc_id: {case_row.get('source_doc_id', '')}",
        f"- bulletin_issue: {case_row.get('bulletin_issue', '')}",
        f"- retrieved_date_utc: {case_row.get('retrieved_date_utc', '')}",
        f"- pdf_sha256: {pdf_sha}",
        "",
        "## Evidence items",
    ]
    for item in items:
        evidence_md_lines.append(f"- [{item['id']}] ({item['source']}) {item['text']}")

    evidence_md = normalize_text("\n".join(evidence_md_lines))
    evidence_md_path = output_dir / "evidence_packet.md"
    evidence_md_path.write_text(evidence_md, encoding="utf-8")

    evidence_json_path = output_dir / "evidence_packet.json"
    evidence_json_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    leakage_path = spec_dir / "leakage_checks.md"
    keywords = _load_keywords(leakage_path)
    warnings: List[str] = []
    for section in DISALLOWED_SECTIONS:
        section_path = extracts_dir / f"{section}.txt"
        if section_path.exists():
            text = section_path.read_text(encoding="utf-8")
            if text.strip() and text.strip() in evidence_md:
                raise ValueError(f"Leakage detected: {section} content in evidence packet")
    for keyword in keywords:
        if keyword and keyword.lower() in evidence_md.lower():
            warnings.append(f"Leakage keyword detected: {keyword}")
    for keyword in LEAKAGE_KEYWORDS:
        if keyword and keyword.lower() in evidence_md.lower():
            raise ValueError(f"Leakage keyword detected: {keyword}")

    return evidence_md_path, evidence_json_path, warnings
