from __future__ import annotations

import types

import pytest

import abductio_core.adapters.openai_llm as m


class DummyClient:
    def __init__(self, response):
        self._response = response

    def complete_json(self, *, system: str, user: str):
        return self._response


def test_openai_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        m.OpenAIJsonClient(model="gpt-4.1-mini")


def test_openai_client_import_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    def _fail_import(name):
        raise ImportError("missing")

    monkeypatch.setattr(m.importlib, "import_module", _fail_import)
    with pytest.raises(RuntimeError):
        m.OpenAIJsonClient(model="gpt-4.1-mini")


def test_validate_evaluation_error_branches() -> None:
    with pytest.raises(RuntimeError):
        m._validate_evaluation(
            {
                "p": "x",
                "A": 1,
                "B": 1,
                "C": 1,
                "D": 1,
                "evidence_ids": ["EV-1"],
                "discriminator_ids": [],
                "discriminator_payloads": [],
                "entailment": "NEUTRAL",
                "evidence_quality": "direct",
                "reasoning_summary": "Supported by EV-1.",
                "defeaters": ["None."],
                "uncertainty_source": "Limited evidence.",
                "assumptions": [],
            }
        )
    with pytest.raises(RuntimeError):
        m._validate_evaluation(
            {
                "p": 0.1,
                "A": True,
                "B": 1,
                "C": 1,
                "D": 1,
                "evidence_ids": ["EV-1"],
                "discriminator_ids": [],
                "discriminator_payloads": [],
                "entailment": "NEUTRAL",
                "evidence_quality": "direct",
                "reasoning_summary": "Supported by EV-1.",
                "defeaters": ["None."],
                "uncertainty_source": "Limited evidence.",
                "assumptions": [],
            }
        )
    with pytest.raises(RuntimeError):
        m._validate_evaluation(
            {
                "p": 0.1,
                "A": "x",
                "B": 1,
                "C": 1,
                "D": 1,
                "evidence_ids": ["EV-1"],
                "discriminator_ids": [],
                "discriminator_payloads": [],
                "entailment": "NEUTRAL",
                "evidence_quality": "direct",
                "reasoning_summary": "Supported by EV-1.",
                "defeaters": ["None."],
                "uncertainty_source": "Limited evidence.",
                "assumptions": [],
            }
        )
    with pytest.raises(RuntimeError):
        m._validate_evaluation(
            {
                "p": 0.1,
                "A": 3,
                "B": 1,
                "C": 1,
                "D": 1,
                "evidence_ids": ["EV-1"],
                "discriminator_ids": [],
                "discriminator_payloads": [],
                "entailment": "NEUTRAL",
                "evidence_quality": "direct",
                "reasoning_summary": "Supported by EV-1.",
                "defeaters": ["None."],
                "uncertainty_source": "Limited evidence.",
                "assumptions": [],
            }
        )
    m._validate_evaluation(
        {
            "p": 0.1,
            "A": 1,
            "B": 1,
            "C": 1,
            "D": 1,
            "evidence_ids": [],
            "discriminator_ids": [],
            "discriminator_payloads": [],
            "entailment": "NEUTRAL",
            "evidence_quality": "none",
            "reasoning_summary": "No supporting evidence.",
            "defeaters": ["Would change with new evidence."],
            "uncertainty_source": "No evidence packet.",
            "assumptions": [],
        }
    )


def test_validate_slot_decomposition_error_branches() -> None:
    m._validate_slot_decomposition({"ok": False})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition(
            {"ok": True, "children": [{"child_id": "c1", "statement": "s"}, {"child_id": "c2", "statement": "s"}], "type": "BAD"}
        )
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [], "type": "AND"})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": ["x", "y"], "type": "OR"})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"child_id": "c1"}], "type": "AND", "coupling": 0.8})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"child_id": "c1", "statement": "s"}, {"child_id": "c2", "statement": "s"}], "type": "AND", "coupling": "x"})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"child_id": "c1", "statement": "s"}, {"child_id": "c2", "statement": "s"}], "type": "AND", "coupling": 0.1})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": ["x", {"child_id": "c1", "statement": "s"}], "type": "AND", "coupling": 0.8})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"statement": "s"}, {"child_id": "c2", "statement": "s"}], "type": "AND", "coupling": 0.8})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"child_id": "c1"}, {"child_id": "c2"}], "type": "AND", "coupling": 0.8})
    with pytest.raises(RuntimeError):
        m._validate_slot_decomposition({"ok": True, "children": [{"child_id": "c1", "statement": "s", "role": "BAD"}, {"child_id": "c2", "statement": "s"}], "type": "AND", "coupling": 0.8})


def test_decomposer_slot_and_root_paths() -> None:
    client = DummyClient(
        {
            "ok": True,
            "type": "AND",
            "coupling": 0.8,
            "children": [
                {
                    "child_id": "c1",
                    "statement": "s",
                    "falsifiable": True,
                    "test_procedure": "Check s",
                    "overlap_with_siblings": [],
                },
                {
                    "child_id": "c2",
                    "statement": "s",
                    "falsifiable": True,
                    "test_procedure": "Check s",
                    "overlap_with_siblings": [],
                },
            ],
        }
    )
    port = m.OpenAIDecomposerPort(client=client, required_slots_hint=["feasibility"], scope="c", root_statements={"H1": "root"})
    slot_out = port.decompose("H1:feasibility")
    assert slot_out["children"]

    client2 = DummyClient("not-a-dict")
    port2 = m.OpenAIDecomposerPort(client=client2, required_slots_hint=["feasibility"])
    root_out = port2.decompose("H1")
    assert root_out["ok"] is True
    assert "feasibility_statement" in root_out

    client3 = DummyClient("not-a-dict")
    port3 = m.OpenAIDecomposerPort(client=client3, required_slots_hint=["feasibility"])
    slot_out2 = port3.decompose("H1:feasibility")
    assert slot_out2["children"]


def test_evaluator_paths_and_non_dict_response() -> None:
    client = DummyClient(
        {
            "p": 0.6,
            "A": 1,
            "B": 1,
            "C": 1,
            "D": 1,
            "evidence_ids": ["EV-1"],
            "discriminator_ids": [],
            "discriminator_payloads": [],
            "entailment": "NEUTRAL",
            "evidence_quality": "direct",
            "reasoning_summary": "Supported by EV-1.",
            "defeaters": ["None."],
            "uncertainty_source": "Limited evidence.",
            "assumptions": [],
        }
    )
    port = m.OpenAIEvaluatorPort(client=client, scope="c", root_statements={"H1": "root"})
    out = port.evaluate("H1:feasibility")
    assert out["p"] == 0.6

    bad = DummyClient("not-a-dict")
    port_bad = m.OpenAIEvaluatorPort(client=bad)
    with pytest.raises(RuntimeError):
        port_bad.evaluate("H1:feasibility")
