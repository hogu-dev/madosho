# tests/unit/test_research_agent_llm.py
"""AnyLlmClient wraps any_llm.completion and normalizes its OpenAI-shaped response
into our AssistantTurn. The real completion is monkeypatched (same seam madosho uses)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import research_agent.llm as llm_mod
from research_agent.llm import AnyLlmClient
from research_agent.types import LlmEndpoint


def _fake_completion_factory(captured, message):
    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return fake_completion


def test_forwards_provider_model_creds_and_tools(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="hello", tool_calls=None)
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="openai", model="gpt-x",
                                      api_key="k", api_base="http://h"))
    tools = [{"type": "function", "function": {"name": "search"}}]
    turn = client.complete([{"role": "user", "content": "hi"}], tools)
    assert captured["provider"] == "openai" and captured["model"] == "gpt-x"
    assert captured["api_key"] == "k" and captured["api_base"] == "http://h"
    assert captured["tools"] == tools and captured["tool_choice"] == "auto"
    assert captured["stream"] is False
    assert turn.text == "hello" and turn.tool_calls == []


def test_no_tools_means_no_tool_choice(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="done", tool_calls=None)
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="p", model="m"))
    client.complete([{"role": "user", "content": "x"}], [])
    assert captured["tools"] is None
    assert captured["tool_choice"] is None
    assert "api_key" not in captured and "api_base" not in captured


def test_normalizes_tool_calls(monkeypatch):
    captured = {}
    tc = SimpleNamespace(id="call_1", type="function",
                         function=SimpleNamespace(name="search",
                                                  arguments='{"corpus": "a", "query": "q"}'))
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="p", model="m"))
    turn = client.complete([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert turn.text is None
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert call.id == "call_1" and call.name == "search"
    assert call.arguments == {"corpus": "a", "query": "q"}


def test_bad_tool_arguments_become_empty_dict(monkeypatch):
    captured = {}
    tc = SimpleNamespace(id="c", type="function",
                         function=SimpleNamespace(name="search", arguments="not json"))
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="p", model="m"))
    turn = client.complete([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert turn.tool_calls[0].arguments == {}


def test_anyllm_populates_usage(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="hi", tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return resp

    monkeypatch.setattr(llm_mod, "completion", fake_completion)
    client = AnyLlmClient(LlmEndpoint(provider="openai", model="m"))
    turn = client.complete([{"role": "user", "content": "x"}], [])
    assert turn.usage == {"prompt_tokens": 12, "completion_tokens": 5,
                          "total_tokens": 17}


def test_anyllm_usage_absent_is_none(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="hi", tool_calls=None)
    resp = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    # no usage attribute at all

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return resp

    monkeypatch.setattr(llm_mod, "completion", fake_completion)
    client = AnyLlmClient(LlmEndpoint(provider="openai", model="m"))
    turn = client.complete([{"role": "user", "content": "x"}], [])
    assert turn.usage is None


def test_forwards_reasoning_effort_when_set(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="ok", tool_calls=None)
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="openai", model="m",
                                      reasoning_effort="low"))
    client.complete([{"role": "user", "content": "x"}], [])
    assert captured["reasoning_effort"] == "low"


def test_omits_reasoning_effort_when_unset(monkeypatch):
    captured = {}
    msg = SimpleNamespace(content="ok", tool_calls=None)
    monkeypatch.setattr(llm_mod, "completion", _fake_completion_factory(captured, msg))
    client = AnyLlmClient(LlmEndpoint(provider="openai", model="m"))  # no effort
    client.complete([{"role": "user", "content": "x"}], [])
    assert "reasoning_effort" not in captured   # left to any_llm's default
