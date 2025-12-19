from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Node:
    node_key: str
    statement: str
    role: str
    p: float = 1.0
    k: float = 0.15
    children: List[str] = field(default_factory=list)
    decomp_type: Optional[str] = None
    coupling: Optional[float] = None


@dataclass
class RootHypothesis:
    root_id: str
    statement: str
    exclusion_clause: str
    canonical_id: str
    status: str = "UNSCOPED"
    k_root: float = 0.15
    obligations: Dict[str, Node] = field(default_factory=dict)
    credits_spent: int = 0


@dataclass
class HypothesisSet:
    roots: Dict[str, RootHypothesis] = field(default_factory=dict)
    ledger: Dict[str, float] = field(default_factory=dict)
