# tests/unit/test_corpus_stages.py
"""ingest_file is split into parse_file + index_document so the eval runner can parse
once (OCR never twice) and rebuild only downstream stages. ingest_file must keep
its exact old behavior (it now composes the two)."""
import hashlib
import mimetypes
from pathlib import Path

import madosho
from madosho.core.types import Document, IngestArtifacts, SourceFile

CONFIG = """
corpus: notes
source: {source}
ingest:
  parser: fake-parser
  chunker: fake-chunker
  embedder: hash-embedder
  store: fake-store
  indexes: [bm25, dense]
query:
  - keyword_search: {{k: 10}}
  - semantic_search: {{k: 10}}
  - fuse: {{method: rrf}}
  - rerank: {{model: fake-reranker, top_k: 2}}
"""


def _corpus(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "docs"; src.mkdir()
    (src / "a.txt").write_text("The termination clause requires ninety days notice.")
    cfg = tmp_path / "madosho.yaml"
    cfg.write_text(CONFIG.format(source=src))
    return madosho.open(cfg), src


def _sf(src):
    path = sorted(p for p in Path(src).rglob("*") if p.is_file())[0]
    return SourceFile(path=str(path), content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                      mimetype=mimetypes.guess_type(path)[0] or "application/octet-stream")


def test_parse_file_returns_a_kernel_document(tmp_path, monkeypatch):
    corpus, src = _corpus(tmp_path, monkeypatch)
    doc = corpus.parse_file(_sf(src))
    assert isinstance(doc, Document)
    assert doc.doc_id and doc.blocks


def test_index_document_chunks_embeds_stores_and_returns_artifacts(tmp_path, monkeypatch):
    corpus, src = _corpus(tmp_path, monkeypatch)
    doc = corpus.parse_file(_sf(src))
    artifacts = corpus.index_document(doc)
    assert isinstance(artifacts, IngestArtifacts)
    assert artifacts.doc_id == doc.doc_id and artifacts.chunks
    # stored and queryable
    hits = corpus.query("termination clause notice")
    assert hits and "ninety days" in hits[0].text


def test_ingest_file_still_composes_parse_then_index(tmp_path, monkeypatch):
    corpus, src = _corpus(tmp_path, monkeypatch)
    artifacts = corpus.ingest_file(_sf(src))
    assert isinstance(artifacts, IngestArtifacts) and artifacts.chunks


def test_store_property_exposes_the_resolved_store(tmp_path, monkeypatch):
    corpus, _ = _corpus(tmp_path, monkeypatch)
    assert corpus.store is corpus._store


def test_delete_document_removes_its_chunks_from_the_store(tmp_path, monkeypatch):
    corpus, src = _corpus(tmp_path, monkeypatch)
    doc = corpus.parse_file(_sf(src))
    corpus.index_document(doc)
    assert corpus.query("termination clause notice")        # indexed and findable
    corpus.delete_document(doc.doc_id)
    assert corpus.query("termination clause notice") == []  # its chunks are gone


def test_delete_document_is_idempotent_for_unknown_ids(tmp_path, monkeypatch):
    corpus, _ = _corpus(tmp_path, monkeypatch)
    corpus.delete_document("never-ingested")                # no-op, must not raise
