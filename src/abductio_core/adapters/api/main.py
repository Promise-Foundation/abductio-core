from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from abductio_core.adapters.openai_llm import (
    OpenAIDecomposerPort,
    OpenAIEvaluatorPort,
    OpenAIJsonClient,
)
from abductio_core.application.dto import EvidenceItem, RootSpec, SessionConfig, SessionRequest
from abductio_core.application.ports import RunSessionDeps
from abductio_core.application.use_cases.replay_session import replay_session
from abductio_core.application.use_cases.run_session import run_session


def _app_version() -> str:
    try:
        return version("abductio-core")
    except PackageNotFoundError:
        return "0.0.0"


app = FastAPI(
    title="abductio-core API",
    version=_app_version(),
    docs_url=None,
    redoc_url=None,
)

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
    tau: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for declaring a frontier slot confident.",
        examples=[0.7],
    )
    epsilon: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Frontier inclusion tolerance around the leader score.",
        examples=[0.05],
    )
    gamma: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Prior mass assigned to H_other when world_mode is open.",
        examples=[0.2],
    )
    alpha: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Damping factor for blending prior and updated ledger.",
        examples=[0.4],
    )
    beta: float = Field(
        ...,
        ge=0.0,
        description="Evidence weight scale used in log-space updates.",
        examples=[1.0],
    )
    W: float = Field(
        ...,
        gt=0.0,
        description="Maximum absolute log-space weight per slot.",
        examples=[3.0],
    )
    lambda_voi: float = Field(
        ...,
        ge=0.0,
        description="VOI-Lite scheduler exploration term.",
        examples=[0.1],
    )
    world_mode: str = Field(
        "open",
        description="Whether to include H_other absorber ('open' or 'closed').",
        examples=["open"],
    )


class RootSpecIn(BaseModel):
    root_id: str = Field(..., min_length=1, examples=["H1"])
    statement: str = Field(..., min_length=1, examples=["Mechanism A"])
    exclusion_clause: str = Field("", examples=["Not explained by any other root"])


class SessionRequestIn(BaseModel):
    scope: Optional[str] = Field(None, min_length=1, description="Problem scope or claim under evaluation.")
    claim: Optional[str] = Field(None, min_length=1, description="Deprecated alias for scope.")
    roots: List[RootSpecIn] = Field(..., min_length=1, description="Named hypotheses.")
    config: SessionConfigIn
    credits: int = Field(..., ge=0, description="Total credits available for DECOMPOSE/EVALUATE ops.")

    required_slots: Optional[List[Dict[str, Any]]] = None
    run_mode: Optional[str] = None
    run_count: Optional[int] = None
    run_target: Optional[str] = None
    initial_ledger: Optional[Dict[str, float]] = None
    evidence_items: Optional[List[Dict[str, Any]]] = None
    pre_scoped_roots: Optional[List[str]] = None
    slot_k_min: Optional[Dict[str, float]] = None
    slot_initial_p: Optional[Dict[str, float]] = None
    force_scope_fail_root: Optional[str] = None


class ReplayRequestIn(BaseModel):
    audit_trace: List[Dict[str, Any]] = Field(..., min_length=1, description="Audit events to replay.")


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
        client=client,
        scope=req.scope,
        root_statements=root_statements,
        evidence_items=[
            {
                "id": item.id,
                "source": item.source,
                "text": item.text,
                "location": item.location,
                "metadata": dict(item.metadata),
            }
            for item in (req.evidence_items or [])
        ],
    )
    decomposer = OpenAIDecomposerPort(
        client=client,
        required_slots_hint=required_slots_hint,
        scope=req.scope,
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


@app.get("/docs", include_in_schema=False)
def scalar_docs() -> HTMLResponse:
    """Scalar API Reference UI backed by FastAPI's OpenAPI schema."""
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>abductio-core API Reference</title>
    <style>
      html, body { height: 100%; margin: 0; }
      #api-reference { height: 100%; }
    </style>
  </head>
  <body>
    <div id="api-reference"></div>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
    <script>
      Scalar.createApiReference(document.getElementById('api-reference'), {
        spec: { url: '/openapi.json' }
      });
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)


@app.post(
    "/v1/sessions/run",
    summary="Run an ABDUCTIO session",
    description="Executes the ABDUCTIO engine using the provided roots, config, and credits.",
)
def run_session_endpoint(body: SessionRequestIn) -> Dict[str, Any]:
    scope = body.scope or body.claim
    if not scope:
        raise HTTPException(status_code=400, detail="scope is required")
    req = SessionRequest(
        scope=scope,
        roots=[RootSpec(r.root_id, r.statement, r.exclusion_clause) for r in body.roots],
        config=SessionConfig(
            tau=body.config.tau,
            epsilon=body.config.epsilon,
            gamma=body.config.gamma,
            alpha=body.config.alpha,
            beta=body.config.beta,
            W=body.config.W,
            lambda_voi=body.config.lambda_voi,
            world_mode=body.config.world_mode,
        ),
        credits=body.credits,
        required_slots=body.required_slots,
        run_mode=body.run_mode,
        run_count=body.run_count,
        run_target=body.run_target,
        initial_ledger=body.initial_ledger,
        evidence_items=[
            EvidenceItem(
                id=str(item.get("id") or item.get("evidence_id") or ""),
                source=str(item.get("source", "")),
                text=str(item.get("text", "")),
                location=item.get("location"),
                metadata=dict(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {},
            )
            for item in (body.evidence_items or [])
            if isinstance(item, dict) and (item.get("id") or item.get("evidence_id"))
        ],
        pre_scoped_roots=body.pre_scoped_roots,
        slot_k_min=body.slot_k_min,
        slot_initial_p=body.slot_initial_p,
        force_scope_fail_root=body.force_scope_fail_root,
    )

    try:
        deps = _build_deps(req)
        result = run_session(req, deps)
        payload = result.to_dict_view()
        if body.claim and not body.scope:
            payload.setdefault("meta", {}).setdefault("warnings", []).append(
                "claim is deprecated; use scope"
            )
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"run_session failed: {exc}") from exc


@app.post(
    "/v1/sessions/replay",
    summary="Replay an ABDUCTIO session",
    description="Replays a session from an audit trace to reproduce the final ledger and stop reason.",
)
def replay_session_endpoint(body: ReplayRequestIn) -> Dict[str, Any]:
    try:
        result = replay_session(body.audit_trace)
        return result.to_dict_view()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"replay_session failed: {exc}") from exc
