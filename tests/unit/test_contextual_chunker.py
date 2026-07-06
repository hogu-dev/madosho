import logging
from pathlib import Path

import pytest

from madosho.adapters.text.contextual_chunker import ContextualChunker
from madosho.core.meta import ComponentKind
from madosho.core.protocols import RuntimeContext
from madosho.core.registry import Registry
from madosho.core.types import Block, BlockKind, Document, Provenance, SourceFile
from madosho.testing.contracts import ChunkerContractTests


class FakeLlm:
    """A callable (prompt) -> str standing in for runtime.llm. Records the
    prompts it sees so tests can assert what the chunker sent."""

    def __init__(self, reply: str = "SITUATED CONTEXT", fail: bool = False):
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("llm unavailable")
        return self.reply


def _runtime(llm=None) -> RuntimeContext:
    return RuntimeContext(
        corpus="test", data_dir=Path("/tmp/madosho-ctx"), cache_dir=None,
        logger=logging.getLogger("madosho.test"), llm=llm)


def _doc(blocks: list[Block]) -> Document:
    return Document(
        doc_id="d",
        source=SourceFile(path="d.txt", mimetype="text/plain", content_hash="x"),
        blocks=blocks)


def _heading_doc() -> Document:
    prov = Provenance(source="d.txt", page=2)
    return _doc([
        Block(kind=BlockKind.HEADING, content="Engines", provenance=prov),
        Block(kind=BlockKind.TEXT, content="The F-1 produced great thrust.", provenance=prov),
    ])


class TestContextualChunkerContract(ChunkerContractTests):
    @pytest.fixture
    def chunker(self):
        return ContextualChunker(
            options=ContextualChunker.Options(),
            runtime=_runtime(llm=FakeLlm()))


def test_llm_context_is_prepended_to_prefix():
    llm = FakeLlm(reply="About rocket engines.")
    chunks = ContextualChunker(runtime=_runtime(llm=llm)).chunk(_heading_doc())
    assert chunks[0].context_prefix.startswith("About rocket engines.")
    # the base chunker's heading prefix is preserved underneath the situated context
    assert "Engines" in chunks[0].context_prefix
    # the body text itself is untouched (context rides only in the prefix)
    assert chunks[0].text == "The F-1 produced great thrust."


def test_llm_prompt_includes_whole_doc_and_the_chunk():
    llm = FakeLlm()
    ContextualChunker(runtime=_runtime(llm=llm)).chunk(_heading_doc())
    assert llm.prompts, "the chunker should have called the llm at least once"
    p = llm.prompts[0]
    assert "The F-1 produced great thrust." in p   # the chunk
    assert "Engines" in p                           # whole-doc content


def test_embed_text_carries_the_situated_context():
    llm = FakeLlm(reply="Section on engines.")
    chunks = ContextualChunker(runtime=_runtime(llm=llm)).chunk(_heading_doc())
    assert "Section on engines." in chunks[0].embed_text
    assert "The F-1 produced great thrust." in chunks[0].embed_text


def test_missing_llm_raises_clearly():
    with pytest.raises(Exception) as exc:
        ContextualChunker(runtime=_runtime(llm=None)).chunk(_heading_doc())
    assert "llm" in str(exc.value).lower() or "provider" in str(exc.value).lower()


def test_per_chunk_llm_failure_raises_config_error():
    from madosho.core.errors import ConfigError
    chunker = ContextualChunker(runtime=_runtime(llm=FakeLlm(fail=True)))
    with pytest.raises(ConfigError, match="contextual chunker"):
        chunker.chunk(_heading_doc())


def test_oversized_doc_skips_enrichment():
    llm = FakeLlm()
    opts = ContextualChunker.Options(max_doc_chars=10)
    chunks = ContextualChunker(options=opts, runtime=_runtime(llm=llm)).chunk(_heading_doc())
    assert llm.prompts == []                         # llm never called
    assert chunks[0].context_prefix == "Engines"     # base prefix intact


def test_options_pass_through_to_base_chunker():
    text = " ".join(f"word{i}" for i in range(300))
    prov = Provenance(source="d.txt", page=1)
    doc = _doc([Block(kind=BlockKind.TEXT, content=text, provenance=prov)])
    opts = ContextualChunker.Options(max_chars=120, overlap=30)
    chunks = ContextualChunker(options=opts, runtime=_runtime(llm=FakeLlm())).chunk(doc)
    assert len(chunks) > 1
    assert all(len(c.text) <= 120 for c in chunks)


def test_registered_and_resolvable():
    reg = Registry()
    assert "contextual" in reg.names(ComponentKind.CHUNKER)
    assert reg.load_class(ComponentKind.CHUNKER, "contextual") is ContextualChunker
