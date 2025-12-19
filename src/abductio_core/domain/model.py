from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class RootHypothesis:
    root_id: str
    statement: str
    exclusion_clause: str
    canonical_id: str
    status: str = "UNSCOPED"
    k_root: float = 0.15


@dataclass
class HypothesisSet:
    roots: Dict[str, RootHypothesis] = field(default_factory=dict)
    ledger: Dict[str, float] = field(default_factory=dict)
