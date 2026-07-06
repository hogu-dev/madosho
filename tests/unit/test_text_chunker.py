import pytest

from madosho.adapters.text.chunker import RecursiveTextChunker
from madosho.core.meta import ComponentKind
from madosho.core.registry import Registry
from madosho.core.types import Block, BlockKind, Document, Provenance, SourceFile
from madosho.testing.contracts import ChunkerContractTests


class TestRecursiveTextChunkerContract(ChunkerContractTests):
    @pytest.fixture
    def chunker(self):
        return RecursiveTextChunker.make()


def _doc(blocks: list[Block]) -> Document:
    return Document(
        doc_id="d",
        source=SourceFile(path="d.txt", mimetype="text/plain", content_hash="x"),
        blocks=blocks)


def _text_doc(text: str, page: int = 1) -> Document:
    prov = Provenance(source="d.txt", page=page)
    return _doc([Block(kind=BlockKind.TEXT, content=text, provenance=prov)])


def test_short_doc_yields_single_chunk():
    chunks = RecursiveTextChunker.make().chunk(_text_doc("a short paragraph."))
    assert len(chunks) == 1
    assert chunks[0].text == "a short paragraph."
    assert chunks[0].position == 0
    assert chunks[0].doc_id == "d"


def test_long_text_splits_into_bounded_sequential_chunks():
    text = " ".join(f"Sentence number {i} carries a few words." for i in range(60))
    chunks = RecursiveTextChunker.make(max_chars=200, overlap=40).chunk(_text_doc(text))
    assert len(chunks) > 1
    assert all(len(c.text) <= 200 for c in chunks)               # budget respected
    assert [c.position for c in chunks] == list(range(len(chunks)))  # sequential
    assert len({c.id for c in chunks}) == len(chunks)            # unique ids


def test_overlap_carries_tail_between_chunks():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = RecursiveTextChunker.make(max_chars=120, overlap=30).chunk(_text_doc(text))
    assert len(chunks) >= 2
    # some word at the end of a chunk should reappear at the start of the next
    overlapped = any(
        any(tok in chunks[i + 1].text for tok in chunks[i].text.split()[-3:])
        for i in range(len(chunks) - 1))
    assert overlapped


def test_no_overlap_when_overlap_is_zero():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = RecursiveTextChunker.make(max_chars=120, overlap=0).chunk(_text_doc(text))
    assert all(len(c.text) <= 120 for c in chunks)


def test_heading_becomes_context_prefix_and_scopes_chunks():
    prov = Provenance(source="d.txt", page=2)
    doc = _doc([
        Block(kind=BlockKind.HEADING, content="Engines", provenance=prov),
        Block(kind=BlockKind.TEXT, content="The F-1 produced great thrust.", provenance=prov),
    ])
    chunks = RecursiveTextChunker.make().chunk(doc)
    assert chunks[0].context_prefix == "Engines"
    assert chunks[0].page == 2
    assert "Engines" not in chunks[0].text   # heading is the prefix, not the body


def test_two_headings_produce_separately_scoped_chunks():
    prov = Provenance(source="d.txt", page=1)
    doc = _doc([
        Block(kind=BlockKind.HEADING, content="Alpha", provenance=prov),
        Block(kind=BlockKind.TEXT, content="alpha body text.", provenance=prov),
        Block(kind=BlockKind.HEADING, content="Beta", provenance=prov),
        Block(kind=BlockKind.TEXT, content="beta body text.", provenance=prov),
    ])
    chunks = RecursiveTextChunker.make().chunk(doc)
    prefixes = {c.context_prefix for c in chunks}
    assert prefixes == {"Alpha", "Beta"}
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_no_heading_uses_empty_prefix():
    chunks = RecursiveTextChunker.make().chunk(_text_doc("body without a heading."))
    assert chunks[0].context_prefix == ""


def test_empty_and_whitespace_only_docs_yield_no_chunks():
    assert RecursiveTextChunker.make().chunk(_doc([])) == []
    assert RecursiveTextChunker.make().chunk(_text_doc("   \n  ")) == []


def test_very_long_unbroken_token_is_hard_split():
    chunks = RecursiveTextChunker.make(max_chars=50, overlap=0).chunk(_text_doc("x" * 230))
    assert len(chunks) >= 5
    assert all(len(c.text) <= 50 for c in chunks)


def test_overlap_must_be_smaller_than_max_chars():
    with pytest.raises(ValueError):
        RecursiveTextChunker.make(max_chars=100, overlap=100)


def test_chunker_is_registered_and_resolvable():
    reg = Registry()
    assert "recursive-text" in reg.names(ComponentKind.CHUNKER)
    assert reg.load_class(ComponentKind.CHUNKER, "recursive-text") is RecursiveTextChunker


def test_second_embedder_is_registered():
    # check the SPEC only -- do not load_class (importing the embedder module
    # would pull heavy model deps the fast suite does not install)
    reg = Registry()
    assert "all-minilm-l6-v2" in reg.names(ComponentKind.EMBEDDER)
    spec = reg.spec(ComponentKind.EMBEDDER, "all-minilm-l6-v2")
    assert spec.target == "madosho.adapters.st_models.embedder:MiniLmEmbedder"
