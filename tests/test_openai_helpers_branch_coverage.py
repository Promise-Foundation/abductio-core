from __future__ import annotations

import json
import types
from typing import Optional

import pytest

import abductio_core.adapters.openai_llm as m


def test_first_text_uses_output_text_when_present() -> None:
    resp = types.SimpleNamespace(output_text="hello")
    assert m._first_text(resp) == "hello"


def test_first_text_uses_output_content_text_when_present() -> None:
    resp = types.SimpleNamespace(output=[types.SimpleNamespace(content=[types.SimpleNamespace(text="hi")])])
    assert m._first_text(resp) == "hi"


def test_first_text_falls_back_to_empty() -> None:
    resp = types.SimpleNamespace(output=None)
    assert m._first_text(resp) == ""


def test_chat_text_reads_choices_message_content() -> None:
    resp = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="yo"))])
    assert m._chat_text(resp) == "yo"


def test_chat_text_handles_exceptions() -> None:
    class _Bad:
        @property
        def choices(self):
            raise RuntimeError("boom")

    assert m._chat_text(_Bad()) == ""


def test_parse_node_key_variants() -> None:
    assert m._parse_node_key("H1") == ("H1", None, None)
    assert m._parse_node_key("H1:feasibility") == ("H1", "feasibility", None)
    assert m._parse_node_key("H1:fit:c1") == ("H1", "fit", "c1")


class _FakeResponses:
    def __init__(self, payload_text: Optional[str], raise_exc: Optional[Exception] = None):
        self._payload_text = payload_text
        self._raise_exc = raise_exc

    def create(self, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return types.SimpleNamespace(output_text=self._payload_text)


class _FakeChatCompletions:
    def __init__(self, payload_text: Optional[str], raise_exc: Optional[Exception] = None):
        self._payload_text = payload_text
        self._raise_exc = raise_exc

    def create(self, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=self._payload_text))]
        )


class _FakeChat:
    def __init__(self, payload_text: Optional[str], raise_exc: Optional[Exception] = None):
        self.completions = _FakeChatCompletions(payload_text, raise_exc)


class _FakeOpenAI:
    def __init__(self, *, responses_text=None, chat_text=None, responses_exc=None, chat_exc=None):
        self.responses = _FakeResponses(responses_text, responses_exc)
        self.chat = _FakeChat(chat_text, chat_exc)


class _FakeOpenAIClass:
    def __init__(self, client: _FakeOpenAI):
        self._client = client

    def __call__(self, api_key, timeout):
        return self._client


def _install_fake_openai(monkeypatch, client: _FakeOpenAI) -> None:
    fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAIClass(client))
    monkeypatch.setattr(m.importlib, "import_module", lambda name: fake_module)


def test_complete_json_uses_responses_api_success(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    _install_fake_openai(monkeypatch, _FakeOpenAI(responses_text=json.dumps({"ok": True})))
    client = m.OpenAIJsonClient(model="gpt-4.1-mini")
    out = client.complete_json(system="s", user="u")
    assert out == {"ok": True}


def test_complete_json_falls_back_to_chat_completions(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    _install_fake_openai(monkeypatch, _FakeOpenAI(responses_text="", chat_text=json.dumps({"ok": True, "x": 1})))
    client = m.OpenAIJsonClient(model="gpt-4.1-mini")
    out = client.complete_json(system="s", user="u")
    assert out["ok"] is True
    assert out["x"] == 1


def test_complete_json_retries_then_raises(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    _install_fake_openai(
        monkeypatch,
        _FakeOpenAI(responses_exc=RuntimeError("boom"), chat_exc=RuntimeError("boom2")),
    )
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    client = m.OpenAIJsonClient(model="gpt-4.1-mini", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(RuntimeError):
        client.complete_json(system="s", user="u")


def test_complete_json_errors_when_openai_missing(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(m.importlib, "import_module", lambda name: types.SimpleNamespace(OpenAI=None))
    with pytest.raises(RuntimeError):
        m.OpenAIJsonClient(model="gpt-4.1-mini")


def test_complete_json_retries_after_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    class _SequencedResponses:
        def __init__(self):
            self._calls = 0

        def create(self, **kwargs):
            self._calls += 1
            payload = "not json" if self._calls == 1 else json.dumps({"ok": True})
            return types.SimpleNamespace(output_text=payload)

    class _SequencedOpenAI:
        def __init__(self):
            self.responses = _SequencedResponses()
            self.chat = _FakeChat(None, None)

    fake_module = types.SimpleNamespace(OpenAI=lambda api_key, timeout: _SequencedOpenAI())
    monkeypatch.setattr(m.importlib, "import_module", lambda name: fake_module)
    monkeypatch.setattr(m.time, "sleep", lambda _: None)
    client = m.OpenAIJsonClient(model="gpt-4.1-mini", max_retries=2, retry_backoff_s=0.0)
    out = client.complete_json(system="s", user="u")
    assert out == {"ok": True}
