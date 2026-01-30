# abductio-core

ABDUCTIO MVP core engine: deterministic scheduling, ledger updates, and a strict
application boundary. You supply evaluator/decomposer/audit ports; the engine
handles orchestration and invariant enforcement.

**What ABDUCTIO does**: Evaluates a MECE (mutually exclusive, collectively exhaustive)
set of hypotheses about a question/phenomenon/case (the "scope") under credit constraints,
with permutation-invariant scheduling and mandatory template-based decomposition to
prevent asymmetric scrutiny.

Project status: core engine library. The HTTP API lives in `abductio-service`.
See `architecture.md` and `docs/white_paper.org` for the spec.

## Install

Requires Python 3.11+.

From PyPI:
```bash
pip install abductio-core
```

Optional OpenAI adapter dependency (used by `abductio_core.adapters.openai_llm`):
```bash
pip install abductio-core[e2e]
```

Local path install (for use inside another codebase):
```bash
pip install /path/to/abductio-core
```

Editable install for local development:
```bash
pip install -e /path/to/abductio-core
```

If you host this repo, you can also install directly from VCS:
```bash
pip install git+ssh://<your-host>/<org>/abductio-core.git
```

## Quickstart

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent

@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)
    def append(self, event: AuditEvent) -> None:
        self.events.append(event)

@dataclass
class NoChildrenDecomposer:
    def decompose(self, target_id: str) -> Dict[str, Any]:
        if ":" in target_id:
            return {"ok": True, "type": "AND", "coupling": 0.80, "children": []}
        return {"ok": True, "feasibility_statement": f"{target_id} feasible"}

@dataclass
class SimpleEvaluator:
    def evaluate(self, node_key: str) -> Dict[str, Any]:
        return {"p": 0.8, "A": 1, "B": 1, "C": 1, "D": 1, "evidence_refs": "ref1"}

# Define the question/phenomenon you're evaluating (the "scope")
# and the competing hypotheses
request = SessionRequest(
    scope="Germany's GDP trajectory in 2026",  # What the hypotheses are about
    roots=[
        RootSpec("H_grow", "Economy will grow", "Not flat or shrink"),
        RootSpec("H_flat", "Economy will be flat", "Not grow or shrink"),
        RootSpec("H_shrink", "Economy will shrink", "Not grow or flat"),
    ],
    config=SessionConfig(
        tau=0.70,
        epsilon=0.05,
        gamma=0.20,
        alpha=0.40,
        beta=1.0,
        W=3.0,
        lambda_voi=0.10,
        world_mode="open",
    ),
    credits=10,
    required_slots=[{"slot_key": "feasibility", "role": "NEC"}],
)

result = run_session(
    request,
    RunSessionDeps(
        evaluator=SimpleEvaluator(),
        decomposer=NoChildrenDecomposer(),
        audit_sink=MemAudit(),
    ),
)

print(f"Ledger: {result.ledger}")
print(f"Stop reason: {result.stop_reason}")
```

## Core Concepts

### Scope vs Hypotheses

- **Scope**: The question, phenomenon, or case being evaluated (e.g., "Germany's 2026 economy")
- **Hypotheses**: The MECE set of alternative explanations/outcomes (e.g., {grow, flat, shrink, other})

The scope is the *frame* for the evaluation session. It's not itself a hypothesis - it's what the hypotheses are competing to explain or predict. This distinction is functional: it tells the engine what partition you're evaluating, enabling proper MECE accounting and H_other handling.

### Permutation Invariance

Given identical inputs (scope, hypotheses, evidence, credit budget), ABDUCTIO produces
identical outputs regardless of:
- Which hypothesis is listed first
- Which hypothesis the user is "focused on"
- The order operations are logged

This is achieved through canonical ordering (hash-based), frontier-only scheduling,
and symmetric obligation templates.

### Obligation Templates

Every hypothesis must be evaluated through the same template of required slots
(default: feasibility, availability, fit, defeater_resistance). This prevents
asymmetric scrutiny where one hypothesis gets loaded with requirements while
rivals remain vague.

## API surface

Public imports from `abductio_core`:
- `RootSpec`, `SessionConfig`, `SessionRequest`
- `SessionResult`, `StopReason`
- `run_session`, `replay_session`

Ports (implement in your app):
- `EvaluatorPort`, `DecomposerPort`, `AuditSinkPort`
- `RunSessionDeps`

## Development

```bash
pip install -e ".[dev]"
pytest
```

Environment variables:
- Copy `.env.example` to `.env` and set `OPENAI_API_KEY` to run E2E tests that hit the OpenAI API.

## Docs

Narrative/source docs live in `docs/` as Org/HTML/PDF assets. These are treated as
source material, not a hosted docs site.

## Versioning

Version is stored in `pyproject.toml` and tagged as `vX.Y.Z` on release. The
`scripts/release.sh` helper updates the version, commits, and tags.

## Release (PyPI)

Recommended: automated publish on tags via GitHub Actions + PyPI trusted publishing.

One-time setup (PyPI):
1. Go to https://pypi.org/manage/account/publishing/
2. Add a trusted publisher for `Promise-Foundation/abductio-core`
3. Select workflow: `.github/workflows/publish.yml`

Release flow:
1. Update `version` in `pyproject.toml`
2. Ensure tests pass: `pytest`
3. Commit changes
4. Tag + push: `git tag vX.Y.Z && git push --tags`

The GitHub Action publishes the build to PyPI on tag push.

Helper script (recommended):
```bash
scripts/release.sh X.Y.Z
git push
git push --tags
```

Manual fallback:
```bash
python -m pip install --upgrade build twine
python -m build
twine upload dist/*
```

Token-based auth:
```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-<your-token>
```

## License

MIT. See `LICENSE`.
