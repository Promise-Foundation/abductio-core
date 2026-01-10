from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class Registry:
    path: Path
    rows: List[Dict[str, str]]
    headers: List[str]

    @classmethod
    def load(cls, path: Path) -> "Registry":
        if not path.exists():
            return cls(path=path, rows=[], headers=[])
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
            headers = list(reader.fieldnames or [])
        return cls(path=path, rows=rows, headers=headers)

    def save(self) -> None:
        if not self.headers:
            raise ValueError("Registry headers are empty")
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.headers)
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)

    def find(self, case_id: str) -> Optional[Dict[str, str]]:
        for row in self.rows:
            if row.get("case_id") == case_id:
                return row
        return None

    def upsert(self, row: Dict[str, str]) -> None:
        case_id = row.get("case_id")
        if not case_id:
            raise ValueError("case_id is required")
        if not self.headers:
            self.headers = list(row.keys())
        for key in row.keys():
            if key not in self.headers:
                self.headers.append(key)
        existing = self.find(case_id)
        if existing:
            existing.update(row)
            return
        self.rows.append(row)


def load_inbox(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def inbox_index(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    index: Dict[str, Dict[str, str]] = {}
    for row in rows:
        filename = row.get("pdf_filename")
        if filename:
            index[filename] = row
    return index
