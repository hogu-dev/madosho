import pytest

from madosho_server import llm
from madosho_server.settings import Settings


def _settings(**kw):
    base = dict(database_url="sqlite://", qdrant_url="", filestore_dir="",
                corpora_dir="")
    base.update(kw)
    return Settings(**base)


def test_complete_raises_without_provider():
    with pytest.raises(llm.ProviderNotConfigured):
        llm.complete([{"role": "user", "content": "hi"}], provider="",
                     model="m", settings=_settings())


def test_complete_forwards_to_any_llm_with_creds(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return "RESULT"

    monkeypatch.setattr(llm, "completion", fake_completion)
    out = llm.complete([{"role": "user", "content": "hi"}], provider="ollama",
                       model="llama3.1",
                       settings=_settings(llm_api_key="k", llm_api_base="b"),
                       stream=True)
    assert out == "RESULT"
    assert captured["provider"] == "ollama"
    assert captured["model"] == "llama3.1"
    assert captured["stream"] is True
    assert captured["api_key"] == "k"
    assert captured["api_base"] == "b"


def test_complete_omits_unset_creds(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm, "completion", lambda **kw: captured.update(kw))
    llm.complete([{"role": "user", "content": "hi"}], provider="openai",
                 model="gpt", settings=_settings())
    assert "api_key" not in captured and "api_base" not in captured


from types import SimpleNamespace


def _delta_events(*texts):
    # what any_llm.responses(stream=True) yields, reduced to the fields we read
    return [SimpleNamespace(type="response.output_text.delta", delta=t) for t in texts]


def test_respond_raises_without_provider():
    with pytest.raises(llm.ProviderNotConfigured):
        llm.respond("hi", provider="", model="m", settings=_settings())


def test_respond_streams_and_joins_deltas(monkeypatch):
    captured = {}

    def fake_responses(**kwargs):
        captured.update(kwargs)
        return iter(_delta_events("MADOSHO ", "VISION")
                    + [SimpleNamespace(type="response.completed")])

    monkeypatch.setattr(llm, "responses", fake_responses)
    out = llm.respond("transcribe", provider="openai", model="gpt-5.5",
                      settings=_settings(llm_api_key="k", llm_api_base="b"))
    assert out == "MADOSHO VISION"
    # ALWAYS streams: the non-streaming path returns an empty output array on at
    # least one Responses proxy in the wild, so stream=True is load-bearing.
    assert captured["stream"] is True
    # bare-string prompts are wrapped to the list form (some proxies 400 on a string)
    assert captured["input_data"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "transcribe"}]}]
    assert captured["provider"] == "openai" and captured["model"] == "gpt-5.5"
    assert captured["api_key"] == "k" and captured["api_base"] == "b"


def test_respond_ignores_non_text_events(monkeypatch):
    events = [SimpleNamespace(type="response.created"),
              SimpleNamespace(type="response.reasoning_text.delta", delta="THINKING"),
              SimpleNamespace(type="response.output_text.delta", delta="answer"),
              SimpleNamespace(type="response.completed")]
    monkeypatch.setattr(llm, "responses", lambda **kw: iter(events))
    assert llm.respond("q", provider="o", model="m", settings=_settings()) == "answer"
