from madosho.core.types import Chunk, Hit
from madosho_server import query_core
from madosho_server.settings import Settings


def _hit(text):
    chunk = Chunk(id="c1", doc_id="d1", text=text, page=1,
                  metadata={"source": "/fs/a.pdf"})
    return Hit(chunk_id="c1", score=1.0, source_index="rrf", chunk=chunk)


class _FakeCorpus:
    def __init__(self, hits):
        self._hits = hits
        self.seen = None

    def query(self, text):
        self.seen = text
        return self._hits


def _settings():
    return Settings(database_url="sqlite://", qdrant_url="", filestore_dir="",
                    corpora_dir="")


def test_generate_retrieves_augments_and_calls_llm(monkeypatch):
    captured = {}

    def fake_complete(messages, provider, model, settings, stream=False,
                      reasoning_effort=None):
        captured["messages"] = messages
        captured["provider"] = provider
        captured["model"] = model
        captured["stream"] = stream
        return "RESULT"

    monkeypatch.setattr(query_core.llm, "complete", fake_complete)
    corpus = _FakeCorpus([_hit("retrieved-context")])

    result, hits = query_core.generate(
        corpus, [{"role": "user", "content": "what is the term?"}],
        provider="ollama", model="llama3.1", settings=_settings())

    assert result == "RESULT"
    assert hits and hits[0].text == "retrieved-context"
    assert corpus.seen == "what is the term?"          # retrieved on the user msg
    assert captured["messages"][0]["role"] == "system"
    assert "retrieved-context" in captured["messages"][0]["content"]
    assert captured["provider"] == "ollama"


def test_generate_passes_template_and_stream(monkeypatch):
    captured = {}
    monkeypatch.setattr(query_core.llm, "complete",
                        lambda messages, provider, model, settings, stream=False,
                        reasoning_effort=None:
                        captured.update(messages=messages, stream=stream))
    corpus = _FakeCorpus([_hit("ctx")])
    query_core.generate(corpus, [{"role": "user", "content": "q"}],
                        provider="p", model="m", settings=_settings(),
                        template="T {context}", stream=True)
    assert captured["messages"][0]["content"].startswith("T ")
    assert captured["stream"] is True
