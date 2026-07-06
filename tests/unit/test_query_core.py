from madosho.core.types import Chunk, Hit
from madosho_server import query_core


def _hit(text, page=1, source="/fs/a.pdf", score=1.0):
    chunk = Chunk(id="c1", doc_id="d1", text=text, page=page,
                  metadata={"source": source})
    return Hit(chunk_id="c1", score=score, source_index="rrf", chunk=chunk)


def test_serialize_hits_shape():
    rows = query_core.serialize_hits([_hit("hello", page=3, source="/fs/x.pdf")])
    assert rows == [{"text": "hello", "score": 1.0, "page": 3,
                     "citation": "x.pdf p.3", "source": "x.pdf"}]


def test_render_context_numbers_hits():
    ctx = query_core.render_context([_hit("alpha"), _hit("beta")])
    assert "[1]" in ctx and "alpha" in ctx
    assert "[2]" in ctx and "beta" in ctx


def test_render_citations_lists_sources():
    footer = query_core.render_citations([_hit("a", page=2, source="/fs/y.pdf")])
    assert "Sources:" in footer
    assert "[1] y.pdf p.2" in footer


def test_render_citations_empty():
    assert query_core.render_citations([]) == ""


def test_augmented_messages_prepends_system_with_context():
    msgs = query_core.augmented_messages(
        [_hit("ctxdata")], [{"role": "user", "content": "Q?"}])
    assert msgs[0]["role"] == "system"
    assert "ctxdata" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "Q?"}


def test_augmented_messages_custom_template():
    msgs = query_core.augmented_messages(
        [_hit("ctxdata")], [{"role": "user", "content": "Q?"}],
        template="PRE {context} POST")
    assert msgs[0]["content"] == "PRE [1] (a.pdf p.1)\nctxdata POST"


def test_last_user_text_picks_last_user():
    text = query_core.last_user_text([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ])
    assert text == "second"


def _hit_with_docid(doc_id, pos, text="t"):
    chunk = Chunk(id=f"{doc_id}-{pos}", doc_id=doc_id, text=text, position=pos,
                  page=1, metadata={"source": "a.pdf"})
    return Hit(chunk_id=chunk.id, score=0.9, source_index="dense", chunk=chunk)


def test_serialize_hits_adds_document_id_and_position():
    hits = [_hit_with_docid("kdoc-1", 3)]
    out = query_core.serialize_hits(hits, doc_id_map={"kdoc-1": 42})
    assert out[0]["document_id"] == 42
    assert out[0]["position"] == 3
    out2 = query_core.serialize_hits(hits, doc_id_map={})
    assert out2[0]["document_id"] is None


def test_serialize_hits_without_map_is_unchanged():
    out = query_core.serialize_hits([_hit_with_docid("kdoc-1", 0)])
    assert "document_id" not in out[0]


from madosho.core.types import display_source


def test_display_source_basenames_a_filestore_path():
    assert display_source("/data/filestore/abc123/contract.pdf") == "contract.pdf"


def test_display_source_leaves_bare_filename_and_none():
    assert display_source("contract.pdf") == "contract.pdf"
    assert display_source(None) is None


def test_hit_citation_uses_basename():
    assert _hit("t", page=4, source="/data/filestore/zz/saturnv.pdf").citation == "saturnv.pdf p.4"


def test_serialize_pipeline_hits_basenames_source():
    from types import SimpleNamespace
    ph = SimpleNamespace(hit=_hit("t", page=1, source="/fs/deep/contract.pdf"),
                         document_id=7, pipeline_id=3, pipeline_name="docling_v2")
    row = query_core.serialize_pipeline_hits([ph])[0]
    assert row["source"] == "contract.pdf"
    assert row["citation"] == "contract.pdf p.1"
