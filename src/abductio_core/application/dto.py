from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SessionConfig:
    tau: float
    epsilon: float
    gamma: float
    alpha: float


@dataclass(frozen=True)
class RootSpec:
    root_id: str
    statement: str
    exclusion_clause: str


@dataclass(frozen=True)
class EvidenceBundle:
    refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionRequest:
    claim: str
    roots: List[RootSpec]
    config: SessionConfig
    credits: int
    required_slots: Optional[List[Dict[str, Any]]] = None
