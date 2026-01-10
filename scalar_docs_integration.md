Below is a complete, “do-this-in-your-repo” guide to make Scalar your real docs solution—so /docs becomes a clean API Reference (auto-generated from your FastAPI OpenAPI schema), and your current scattered Org files become Concept/Whitepaper docs living alongside it (optionally as a proper docs site).

I’m going to assume you mean Scalar API Reference (the OpenAPI renderer) and that you want it reachable at /docs.

0) Target end state
What you’ll get

GET /docs → Scalar API Reference (nice UI, powered by /openapi.json)

GET /openapi.json → your OpenAPI spec (already there via FastAPI defaults)

Your current docs/*.org stop being “the docs site” and become source material:

either kept as-is under docs_src/

or converted to Markdown and served by a lightweight docs site (MkDocs) at /guide or separate hosting

Why this fits your codebase

Your repo already has:

A clean FastAPI app at src/abductio_core/adapters/api/main.py

Pydantic models → OpenAPI generation is automatic

A stable API surface (/v1/sessions/run, /v1/sessions/replay, /healthz)

Scalar is perfect for “make the API docs not embarrassing” without rewriting anything.

1) Replace FastAPI’s default Swagger /docs with Scalar /docs

FastAPI currently already uses /docs for Swagger UI by default—so we’ll disable Swagger/Redoc and install Scalar at /docs.

Edit src/abductio_core/adapters/api/main.py
1.1 Disable built-in docs URLs

Change:

app = FastAPI(title="abductio-core API", version=_app_version())


To:

app = FastAPI(
    title="abductio-core API",
    version=_app_version(),
    docs_url=None,          # disable Swagger UI
    redoc_url=None,         # disable ReDoc
)

1.2 Add a Scalar /docs route

Add imports near the top:

from fastapi.responses import HTMLResponse


Then add this endpoint (near your existing /healthz is fine):

@app.get("/docs", include_in_schema=False)
def scalar_docs() -> HTMLResponse:
    """
    Scalar API Reference UI backed by FastAPI's OpenAPI schema.
    """
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

    <!-- Scalar (CDN) -->
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>

    <script>
      // Mount Scalar into the container
      // If you serve behind a reverse proxy with a prefix, consider making this absolute.
      Scalar.createApiReference(document.getElementById('api-reference'), {
        spec: { url: '/openapi.json' }
      });
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)


✅ That’s enough to get Scalar working in most setups.

2) Verify locally

Run your API (however you currently do—example):

uvicorn abductio_core.adapters.api.main:app --reload --port 8000


Now check:

http://localhost:8000/docs ✅ Scalar UI

http://localhost:8000/openapi.json ✅ schema

http://localhost:8000/healthz ✅ as before

3) Make the OpenAPI output actually good (fast wins)

Scalar renders whatever OpenAPI provides, so the UI quality depends on:

endpoint summaries/descriptions

request/response model field descriptions

examples

3.1 Add endpoint summaries & response models (recommended)

Right now your endpoints return Dict[str, Any]. That works but produces weaker schemas.

At minimum add summary= and description=:

@app.post("/v1/sessions/run", summary="Run an ABDUCTIO session", description="Executes the ABDUCTIO engine using the provided roots, config, and credits.")
def run_session_endpoint(body: SessionRequestIn) -> Dict[str, Any]:
    ...


Do the same for replay.

3.2 Add Field descriptions to Pydantic models

Example:

class SessionConfigIn(BaseModel):
    tau: float = Field(..., ge=0.0, le=1.0, description="Confidence threshold for declaring a frontier slot 'confident'.")
    epsilon: float = Field(..., ge=0.0, le=1.0, description="Frontier inclusion tolerance around the leader score.")
    gamma: float = Field(..., ge=0.0, le=1.0, description="Prior mass assigned to H_other absorber.")
    ...


Scalar will surface these descriptions in the UI.

3.3 Add examples (small but high impact)

Example:

class RootSpecIn(BaseModel):
    root_id: str = Field(..., min_length=1, examples=["H1"])
    statement: str = Field(..., min_length=1, examples=["Mechanism A"])
    exclusion_clause: str = Field("", examples=["Not explained by any other root"])

4) Handle reverse proxy / base-path deployments (important)

If you deploy behind something like:

https://example.com/abductio/…

Then /openapi.json might actually be /abductio/openapi.json.

Option A (simple): configure the URL via env var

In your Scalar HTML, change to:

spec: { url: window.__OPENAPI_URL__ || '/openapi.json' }


And inject __OPENAPI_URL__ from the server:

openapi_url = os.getenv("OPENAPI_URL", "/openapi.json")
...
Scalar.createApiReference(... { spec: { url: '""" + openapi_url + """' } })

Option B: rely on relative URLs

If your docs are served under the same prefix as the schema, a relative path often works:

Use "openapi.json" (no leading slash)

spec: { url: 'openapi.json' }


That makes it relative to /docs → /docs/openapi.json (which might not exist) unless you also expose it there, so typically you’d mount it correctly or use env var.

5) Clean up your repo docs: stop using /docs as a dumping ground

Right now docs/ contains:

.org working notes

white_paper.* outputs

That’s fine, but it shouldn’t collide with your runtime /docs route.

Recommended restructure (minimal friction)

Rename the folder so your repo structure matches intent:

git mv docs docs_src
mkdir -p docs_src/org
# (optional) keep current layout, but "docs_src" signals it's source material


If you don’t want to rename, keep docs/ but treat it as docs_src and never expect it to be web-served.

6) Optional but strong: Add a real “Guide” site for your Org/Whitepaper docs

Scalar is an API reference UI. It’s not a narrative docs system.

Best practice:

Scalar handles /docs (API reference)

MkDocs (or similar) handles /guide (concepts, architecture, whitepapers)

Option A: MkDocs Material (simple, Python-native)
6.1 Add dependencies (choose one)

If you use a requirements file:

pip install mkdocs mkdocs-material


Or add a dev group in pyproject.toml (recommended for your setup).

6.2 Create mkdocs.yml at repo root

Example:

site_name: abductio-core
theme:
  name: material
nav:
  - Overview: README.md
  - Architecture: architecture.md
  - Whitepaper:
      - Whitepaper (PDF): docs_src/white_paper.pdf
      - Whitepaper (HTML): docs_src/white_paper.html
  - Concepts:
      - Changes: docs_src/changes.org
  - API Reference:
      - Scalar: api_reference.md


Create api_reference.md:

# API Reference

The live API reference is served by the API at `/docs`.

6.3 Serve locally
mkdocs serve


Now you have:

narrative docs at http://localhost:8001 (or similar)

API docs at http://localhost:8000/docs

Option B: Embed Scalar inside MkDocs (single docs portal)

If you want one docs site:

host MkDocs (static)

embed Scalar with an HTML block that points at your deployed /openapi.json

This works best when the OpenAPI URL is public and stable.

7) Optional: add a “Docs” command + CI check
7.1 Add a dev script: scripts/dev_api.sh
#!/usr/bin/env bash
set -euo pipefail
uvicorn abductio_core.adapters.api.main:app --reload --port "${PORT:-8000}"

7.2 Add a sanity test (fast, prevents regressions)

Add tests/test_docs_scalar_route.py:

from fastapi.testclient import TestClient
from abductio_core.adapters.api.main import app

def test_docs_route_serves_html():
    c = TestClient(app)
    r = c.get("/docs")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Scalar" in r.text or "api-reference" in r.text

def test_openapi_json_exists():
    c = TestClient(app)
    r = c.get("/openapi.json")
    assert r.status_code == 200
    assert r.json().get("openapi")

8) Small integration notes specific to your API
8.1 CORS

Scalar loads /openapi.json from the same origin → no CORS issue.
If you ever host Scalar elsewhere (like a separate frontend), then you’ll need CORS for GET /openapi.json.

8.2 Auth headers

If later you add API auth, Scalar can be configured to send auth headers / tokens (depends on how you do auth). You’ll typically:

define security schemes in OpenAPI

Scalar will render an auth UI

FastAPI supports this well once your endpoints use dependencies like Depends(oauth2_scheme).

9) Quick checklist

Must-do

 Disable Swagger/Redoc (docs_url=None, redoc_url=None)

 Add /docs route returning Scalar HTML

 Confirm /openapi.json works in your deploy topology

Should-do

 Add endpoint summaries/descriptions

 Add Pydantic Field(..., description=...)

 Rename docs/ → docs_src/ to avoid confusion forever

Nice-to-have

 MkDocs for narrative docs (/guide)

 Simple tests to ensure /docs stays alive
