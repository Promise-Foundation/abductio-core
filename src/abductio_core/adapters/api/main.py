from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from abductio_core.adapters.openai_llm import (
    OpenAIDecomposerPort,
    OpenAIEvaluatorPort,
    OpenAIJsonClient,
)
from abductio_core.application.dto import RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.use_cases.replay_session import replay_session
from abductio_core.application.use_cases.run_session import run_session


def _app_version() -> str:
    try:
        return version("abductio-core")
    except PackageNotFoundError:
        return "0.0.0"


app = FastAPI(title="abductio-core API", version=_app_version())

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
cors_origins = [origin.strip() for origin in cors_origins if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionConfigIn(BaseModel):
    tau: float = Field(..., ge=0.0, le=1.0)
    epsilon: float = Field(..., ge=0.0, le=1.0)
    gamma: float = Field(..., ge=0.0, le=1.0)
    alpha: float = Field(..., ge=0.0, le=1.0)


class RootSpecIn(BaseModel):
    root_id: str = Field(..., min_length=1)
    statement: str = Field(..., min_length=1)
    exclusion_clause: str = ""


class SessionRequestIn(BaseModel):
    claim: str = Field(..., min_length=1)
    roots: List[RootSpecIn] = Field(..., min_length=1)
    config: SessionConfigIn
    credits: int = Field(..., ge=0)

    required_slots: Optional[List[Dict[str, Any]]] = None
    run_mode: Optional[str] = None
    run_count: Optional[int] = None
    run_target: Optional[str] = None
    initial_ledger: Optional[Dict[str, float]] = None
    pre_scoped_roots: Optional[List[str]] = None
    slot_k_min: Optional[Dict[str, float]] = None
    slot_initial_p: Optional[Dict[str, float]] = None
    force_scope_fail_root: Optional[str] = None


class ReplayRequestIn(BaseModel):
    audit_trace: List[Dict[str, Any]] = Field(..., min_length=1)


def _build_openai_client() -> OpenAIJsonClient:
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    timeout_s = float(os.getenv("OPENAI_TIMEOUT_S", "60.0"))
    return OpenAIJsonClient(model=model, temperature=temperature, timeout_s=timeout_s)


def _build_deps(req: SessionRequest) -> RunSessionDeps:
    root_statements = {root.root_id: root.statement for root in req.roots}

    if req.required_slots:
        required_slots_hint = [
            row["slot_key"] for row in req.required_slots if row.get("slot_key")
        ]
    else:
        required_slots_hint = ["feasibility"]

    client = _build_openai_client()

    evaluator = OpenAIEvaluatorPort(
        client=client, claim=req.claim, root_statements=root_statements
    )
    decomposer = OpenAIDecomposerPort(
        client=client,
        required_slots_hint=required_slots_hint,
        claim=req.claim,
        root_statements=root_statements,
    )

    class InMemoryAuditSink:
        def __init__(self) -> None:
            self.events: List[Any] = []

        def append(self, event: Any) -> None:
            self.events.append(event)

    return RunSessionDeps(
        evaluator=evaluator,
        decomposer=decomposer,
        audit_sink=InMemoryAuditSink(),
    )


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/sessions/run")
def run_session_endpoint(body: SessionRequestIn) -> Dict[str, Any]:
    req = SessionRequest(
        claim=body.claim,
        roots=[RootSpec(r.root_id, r.statement, r.exclusion_clause) for r in body.roots],
        config=SessionConfig(
            tau=body.config.tau,
            epsilon=body.config.epsilon,
            gamma=body.config.gamma,
            alpha=body.config.alpha,
        ),
        credits=body.credits,
        required_slots=body.required_slots,
        run_mode=body.run_mode,
        run_count=body.run_count,
        run_target=body.run_target,
        initial_ledger=body.initial_ledger,
        pre_scoped_roots=body.pre_scoped_roots,
        slot_k_min=body.slot_k_min,
        slot_initial_p=body.slot_initial_p,
        force_scope_fail_root=body.force_scope_fail_root,
    )

    try:
        deps = _build_deps(req)
        result = run_session(req, deps)
        return result.to_dict_view()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_session failed: {exc}") from exc


@app.post("/v1/sessions/replay")
def replay_session_endpoint(body: ReplayRequestIn) -> Dict[str, Any]:
    try:
        result = replay_session(body.audit_trace)
        return result.to_dict_view()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"replay_session failed: {exc}") from exc
