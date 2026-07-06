from madosho.core.types import (
    Block, BlockKind, Chunk, Document, EmbeddedChunk, Filters, Hit,
    IndexSpec, IngestReport, Provenance, QueryContext, SourceFile,
)


def make_chunk(**kw):
    base = dict(id="c1", doc_id="d1", text="Hello world", position=0)
    base.update(kw)
    return Chunk(**base)


def test_chunk_embed_text_prefixes_context():
    assert make_chunk(context_prefix="Intro / Scope").embed_text == "Intro / Scope\nHello world"
    assert make_chunk().embed_text == "Hello world"


def test_hit_citation_from_provenance():
    hit = Hit(chunk_id="c1", score=1.0, source_index="bm25",
              chunk=make_chunk(metadata={"source": "a.pdf"}, page=3))
    assert hit.citation == "a.pdf p.3"
    assert hit.text == "Hello world"
    bare = Hit(chunk_id="c1", score=1.0, source_index="bm25", chunk=make_chunk())
    assert bare.citation == "d1"


def test_query_context_caches_query_vector():
    calls = []

    class Emb:
        dims = 2
        def embed(self, texts):
            calls.append(texts)
            return [[1.0, 0.0] for _ in texts]

    ctx = QueryContext(query="q")
    assert ctx.query_vector(Emb()) == [1.0, 0.0]
    assert ctx.query_vector(Emb()) == [1.0, 0.0]
    assert len(calls) == 1


def test_ingest_report_counts():
    rep = IngestReport()
    rep.add_failure("bad.pdf", "boom")
    assert rep.failed == 1 and rep.errors[0].path == "bad.pdf"


def test_document_holds_blocks_with_provenance():
    doc = Document(doc_id="d1",
                   source=SourceFile(path="a.pdf", mimetype="application/pdf", content_hash="x"),
                   blocks=[Block(kind=BlockKind.HEADING, content="T",
                                 provenance=Provenance(source="a.pdf", page=1))])
    assert doc.blocks[0].kind == "heading"


def test_filters_validate():
    f = Filters(equals={"doc_id": "d1"}, any_of={"page": [1, 2]}, ranges={"position": (0, 10)})
    assert f.equals["doc_id"] == "d1"


def test_embedded_chunk_multivectors_default_empty():
    from madosho.core.types import Chunk, EmbeddedChunk
    ec = EmbeddedChunk(chunk=Chunk(id="c1", doc_id="d", text="t"),
                       vectors={"dense": [1.0, 0.0]})
    assert ec.multivectors == {}


def test_embedded_chunk_carries_named_multivectors():
    from madosho.core.types import Chunk, EmbeddedChunk
    ec = EmbeddedChunk(chunk=Chunk(id="c1", doc_id="d", text="t"),
                       vectors={"dense": [1.0, 0.0]},
                       multivectors={"late": [[1.0, 0.0], [0.0, 1.0]]})
    assert ec.multivectors["late"] == [[1.0, 0.0], [0.0, 1.0]]


def test_index_spec_multivectors_default_empty():
    from madosho.core.types import IndexSpec
    spec = IndexSpec(indexes=["bm25", "dense"], vectors={"dense": 8})
    assert spec.multivectors == {}
    spec = IndexSpec(vectors={"dense": 8}, multivectors={"late": 128})
    assert spec.multivectors == {"late": 128}
