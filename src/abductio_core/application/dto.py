from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SessionConfig:
    tau: float
    epsilon: float
    gamma: float
    alpha: float
    beta: float
    W: float
    lambda_voi: float
    world_mode: str


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
class EvidenceItem:
    id: str
    source: str
    text: str
    location: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionRequest:
    scope: str
    roots: List[RootSpec]
    config: SessionConfig
    credits: int
    required_slots: Optional[List[Dict[str, Any]]] = None
    run_mode: Optional[str] = None
    run_count: Optional[int] = None
    run_target: Optional[str] = None
    initial_ledger: Optional[Dict[str, float]] = None
    evidence_items: Optional[List[EvidenceItem]] = None
    pre_scoped_roots: Optional[List[str]] = None
    slot_k_min: Optional[Dict[str, float]] = None
    slot_initial_p: Optional[Dict[str, float]] = None
    force_scope_fail_root: Optional[str] = None
