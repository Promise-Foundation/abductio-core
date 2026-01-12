from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from abductio_core import RootSpec, SessionConfig, SessionRequest, run_session
from abductio_core.adapters.openai_llm import OpenAIDecomposerPort, OpenAIEvaluatorPort, OpenAIJsonClient
from abductio_core.application.ports import RunSessionDeps
from abductio_core.domain.audit import AuditEvent

from .config import corpus_root, spec_root


@dataclass
class MemAudit:
    events: List[AuditEvent] = field(default_factory=list)

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)


def _load_roots(case_dir: Path) -> Tuple[str, List[RootSpec], Dict[str, str]]:
    roots_yaml = case_dir.joinpath("roots.yaml").read_text(encoding="utf-8").splitlines()
    root_set_id = ""
    root_ids: List[str] = []
    for line in roots_yaml:
        line = line.strip()
        if line.startswith("root_set_id:"):
            root_set_id = line.split(":", 1)[1].strip()
        if line.startswith("- id:"):
            root_ids.append(line.split(":", 1)[1].strip())

    library = json.loads(spec_root().joinpath("roots_library.json").read_text(encoding="utf-8"))
    root_set = library.get("root_sets", {}).get(root_set_id, {})
    label_map = {r.get("id"): r.get("label", r.get("id", "")) for r in root_set.get("roots", [])}

    roots: List[RootSpec] = []
    for root_id in root_ids:
        if root_id == "H_OTHER":
            continue
        statement = label_map.get(root_id, root_id)
        roots.append(
            RootSpec(
                root_id=root_id,
                statement=statement,
                exclusion_clause="Not explained by any other root",
            )
        )
    root_statements = {root.root_id: root.statement for root in roots}
    return root_set_id, roots, root_statements


def run_case(
    case_id: str,
    credits: int = 10,
    model: str = "gpt-4.1-mini",
    temperature: float = 0.0,
    timeout_s: float = 60.0,
) -> Path:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set to run ABDUCTIO with OpenAI adapters.")

    case_dir = corpus_root() / "cases" / case_id
    evidence_path = case_dir / "evidence_packet.json"
    if not evidence_path.exists():
        raise FileNotFoundError(f"Missing evidence_packet.json for {case_id}")
    evidence_packet = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence_items = evidence_packet.get("items", [])

    _, roots, root_statements = _load_roots(case_dir)

    client = OpenAIJsonClient(model=model, temperature=temperature, timeout_s=timeout_s)
    evaluator = OpenAIEvaluatorPort(
        client=client,
        scope=case_id,
        root_statements=root_statements,
        evidence_items=[
            {"id": item.get("id", ""), "source": item.get("source", ""), "text": item.get("text", "")}
            for item in evidence_items
        ],
    )
    decomposer = OpenAIDecomposerPort(
        client=client,
        required_slots_hint=["feasibility", "availability", "fit_to_key_features", "defeater_resistance"],
        scope=case_id,
        root_statements=root_statements,
    )

    audit = MemAudit()
    deps = RunSessionDeps(evaluator=evaluator, decomposer=decomposer, audit_sink=audit)

    request = SessionRequest(
        scope=case_id,
        roots=roots,
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
        credits=credits,
        required_slots=[
            {"slot_key": "feasibility", "role": "NEC"},
            {"slot_key": "availability", "role": "NEC"},
            {"slot_key": "fit_to_key_features", "role": "NEC"},
            {"slot_key": "defeater_resistance", "role": "NEC"},
        ],
        evidence_items=evidence_items,
    )

    result = run_session(request, deps)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = case_dir / "runs" / "abductio" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "case_id": case_id,
        "run_id": run_id,
        "model": model,
        "temperature": temperature,
        "timeout_s": timeout_s,
        "credits": credits,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    run_dir.joinpath("run_meta.json").write_text(
        json.dumps(run_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("request.json").write_text(
        json.dumps(asdict(request), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("result.json").write_text(
        json.dumps(result.to_dict_view(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run_dir.joinpath("audit_trace.json").write_text(
        json.dumps(
            [{"event_type": event.event_type, "payload": event.payload} for event in audit.events],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return run_dir
