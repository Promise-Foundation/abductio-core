# abductio-core

ABDUCTIO MVP core engine: deterministic scheduling, ledger updates, and a strict
application boundary. You supply evaluator/decomposer/audit ports; the engine
handles orchestration and invariant enforcement.

Project status: library-only (no CLI/API layer yet). See `architecture.md` and
`docs/white_paper.org` for the spec.

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


request = SessionRequest(
    scope="Example scope",
    roots=[RootSpec("H1", "Mechanism A", "x")],
    config=SessionConfig(tau=0.70, epsilon=0.05, gamma=0.20, alpha=0.40),
    credits=5,
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

print(result)
```

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
pytest
```

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

Helper script:

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
