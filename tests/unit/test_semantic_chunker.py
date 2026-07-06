# tests/unit/test_semantic_chunker.py
import logging
import pathlib

import pytest

from madosho.adapters.text.semantic_chunker import SemanticChunker
from madosho.core.errors import ConfigError
from madosho.core.protocols import RuntimeContext
from madosho.core.types import Block, BlockKind, Document, Provenance, SourceFile


def _doc(*sentences_blocks):
    """Build a Document from (kind, text) tuples as blocks on page 1."""
    blocks = [Block(kind=k, content=t, provenance=Provenance(source="x.txt", page=1))
              for k, t in sentences_blocks]
    src = SourceFile(path="x.txt", mimetype="text/plain", content_hash="h")
    return Document(doc_id="d1", source=src, blocks=blocks)


class TopicEmbedder:
    """Test embedder: sentences containing 'alpha' map to one axis, 'beta' to
    another, so within-topic distance is 0 and the alpha->beta seam is 1."""
    dims = 2
    def embed(self, texts):
        out = []
        for t in texts:
            if "beta" in t.lower():
                out.append([0.0, 1.0])
            else:
                out.append([1.0, 0.0])
        return out


def _runtime(embedder=None):
    return RuntimeContext(corpus="c", data_dir=pathlib.Path("/tmp"),
                          cache_dir=None, logger=logging.getLogger("t"),
                          embedder=embedder)


def test_breakpoint_lands_at_topic_shift():
    body = "alpha one. alpha two. beta one. beta two."
    doc = _doc((BlockKind.TEXT, body))
    ch = SemanticChunker(SemanticChunker.Options(buffer_size=0, min_chars=0),
                         runtime=_runtime(TopicEmbedder()))
    chunks = ch.chunk(doc)
    assert len(chunks) == 2
    assert "alpha" in chunks[0].text and "beta" not in chunks[0].text
    assert "beta" in chunks[1].text


def test_no_shift_section_splits_on_max_chars():
    body = ". ".join([f"alpha {i}" for i in range(200)]) + "."
    doc = _doc((BlockKind.TEXT, body))
    ch = SemanticChunker(SemanticChunker.Options(buffer_size=0, min_chars=0, max_chars=300),
                         runtime=_runtime(TopicEmbedder()))
    chunks = ch.chunk(doc)
    assert len(chunks) > 1
    assert all(len(c.text) <= 300 for c in chunks)


def test_tiny_segment_merges_forward_under_min_chars():
    # Topics A, A, B -> distances [0.0, 1.0]; percentile(0.95) ~= 0.95 so a cut
    # fires after sentence 2, yielding two segments ("alpha one alpha two",
    # "beta three"). Both are well under min_chars=500, so _merge_small folds
    # them back into ONE chunk. The single chunk must contain BOTH topics, which
    # proves the post-cut merge actually ran (not merely an absent cut).
    body = "alpha one. alpha two. beta three."
    doc = _doc((BlockKind.TEXT, body))
    ch = SemanticChunker(SemanticChunker.Options(buffer_size=0, min_chars=500),
                         runtime=_runtime(TopicEmbedder()))
    chunks = ch.chunk(doc)
    assert len(chunks) == 1
    assert "alpha" in chunks[0].text and "beta" in chunks[0].text


def test_heading_scopes_context_prefix():
    doc = _doc((BlockKind.HEADING, "Section A"), (BlockKind.TEXT, "alpha one. alpha two."))
    ch = SemanticChunker(SemanticChunker.Options(buffer_size=0, min_chars=0),
                         runtime=_runtime(TopicEmbedder()))
    chunks = ch.chunk(doc)
    assert chunks and all(c.context_prefix == "Section A" for c in chunks)


def test_missing_embedder_fails_loud():
    doc = _doc((BlockKind.TEXT, "alpha one. beta two."))
    ch = SemanticChunker(runtime=_runtime(embedder=None))
    with pytest.raises(ConfigError):
        ch.chunk(doc)


def test_options_reject_out_of_range_percentile():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SemanticChunker.Options(breakpoint_percentile=150)
    with pytest.raises(ValidationError):
        SemanticChunker.Options(max_chars=0)


def test_resolvable_by_registry_with_options():
    from madosho.core.meta import ComponentKind
    from madosho.core.registry import Registry
    from madosho.core.hooks import ResolutionContext
    reg = Registry()
    obj = reg.resolve(ComponentKind.CHUNKER, "semantic", {"breakpoint_percentile": 90.0},
                      _runtime(TopicEmbedder()), ResolutionContext(corpus="c", config_path=None))
    assert isinstance(obj, SemanticChunker)
    assert obj.options.breakpoint_percentile == 90.0
    with pytest.raises(Exception):
        reg.resolve(ComponentKind.CHUNKER, "semantic", {"bogus": 1},
                    _runtime(TopicEmbedder()), ResolutionContext(corpus="c", config_path=None))
