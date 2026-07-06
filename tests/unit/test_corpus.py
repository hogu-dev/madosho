import pytest

import madosho
from madosho.core.errors import ConfigError

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


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)        # .madosho/ state lands in tmp
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("The termination clause requires ninety days notice.")
    (src / "b.txt").write_text("Payment is due in thirty days.\n\nLate fees apply after that.")
    cfg = tmp_path / "madosho.yaml"
    cfg.write_text(CONFIG.format(source=src))
    return tmp_path, src, cfg


def test_open_resolves_everything_up_front(corpus_dir):
    _, _, cfg = corpus_dir
    corpus = madosho.open(cfg)
    assert corpus.name == "notes"


def test_open_fails_fast_on_unknown_component(corpus_dir):
    tmp, _, cfg = corpus_dir
    bad = tmp / "bad.yaml"
    bad.write_text(cfg.read_text().replace("fake-parser", "no-such-parser"))
    with pytest.raises(ConfigError, match="no-such-parser"):
        madosho.open(bad)


def test_open_fails_fast_on_bad_operator_params(corpus_dir):
    tmp, _, cfg = corpus_dir
    bad = tmp / "bad.yaml"
    bad.write_text(cfg.read_text().replace("{k: 10}", "{k: ten}", 1))
    with pytest.raises(ConfigError):
        madosho.open(bad)


def test_ingest_then_query_end_to_end_on_fakes(corpus_dir):
    _, _, cfg = corpus_dir
    corpus = madosho.open(cfg)
    report = corpus.ingest()
    assert report.processed == 2 and report.failed == 0
    hits = corpus.query("termination clause notice")
    assert hits and "ninety days" in hits[0].text
    assert "a.txt" in hits[0].citation


def test_reingest_skips_unchanged_files(corpus_dir):
    _, src, cfg = corpus_dir
    corpus = madosho.open(cfg)
    corpus.ingest()
    report = corpus.ingest()
    assert report.processed == 0 and report.skipped == 2

    (src / "a.txt").write_text("The termination clause requires thirty days notice.")
    report = madosho.open(cfg).ingest()      # fresh open: state must persist on disk
    assert report.processed == 1 and report.skipped == 1


def test_ingest_is_fail_soft(corpus_dir):
    _, src, cfg = corpus_dir
    (src / "broken.bin").write_bytes(b"\x00\x01")      # unsupported -> skipped, not failed
    corpus = madosho.open(cfg)
    report = corpus.ingest()
    assert report.processed == 2 and report.skipped == 1 and report.failed == 0


def test_parser_crash_is_recorded_not_raised(corpus_dir, monkeypatch):
    _, src, cfg = corpus_dir
    corpus = madosho.open(cfg)

    def boom(file):
        raise RuntimeError("corrupt file")

    monkeypatch.setattr(corpus._parser, "parse", boom)
    report = corpus.ingest()
    assert report.failed == 2 and "corrupt file" in report.errors[0].error


def test_missing_source_dir_is_a_clear_error(corpus_dir):
    tmp, src, cfg = corpus_dir
    import shutil
    shutil.rmtree(src)
    from madosho.core.errors import MadoshoError
    with pytest.raises(MadoshoError, match="source directory"):
        madosho.open(cfg).ingest()


def test_corrupt_manifest_is_a_clear_error(corpus_dir):
    from madosho.core.errors import MadoshoError
    _, _, cfg = corpus_dir
    corpus = madosho.open(cfg)
    corpus.ingest()
    corpus._manifest_path.write_text("{ not json")
    with pytest.raises(MadoshoError, match="corrupt"):
        corpus.ingest()


def test_state_dir_anchored_to_config_not_cwd(corpus_dir, tmp_path, monkeypatch):
    tmp, _, cfg = corpus_dir
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    corpus = madosho.open(cfg)
    corpus.ingest()
    assert (tmp / ".madosho" / "notes" / "manifest.json").exists()
    assert not (elsewhere / ".madosho").exists()


def test_model_cache_defaults_to_shared_library_cache(corpus_dir):
    tmp, _, cfg = corpus_dir
    corpus = madosho.open(cfg)
    # None -> model adapters use the HF default cache, shared across corpora;
    # only state (.madosho/<corpus>/) is anchored next to the config
    assert corpus._runtime.cache_dir is None
    corpus.ingest()
    assert not (tmp / ".madosho" / "cache").exists()


def test_relative_source_anchored_to_config_not_cwd(corpus_dir, tmp_path, monkeypatch):
    tmp, src, cfg = corpus_dir
    cfg.write_text(cfg.read_text().replace(str(src), "./docs"))
    elsewhere = tmp_path / "elsewhere"
    decoy = elsewhere / "docs"                 # a different ./docs tree under the cwd
    decoy.mkdir(parents=True)
    (decoy / "decoy.txt").write_text("the wrong tree")
    monkeypatch.chdir(elsewhere)
    corpus = madosho.open(cfg)
    report = corpus.ingest()
    assert report.processed == 2 and report.failed == 0   # a.txt + b.txt next to the config
    hits = corpus.query("termination clause notice")
    assert "a.txt" in hits[0].citation


def test_zero_chunk_ingest_warns(corpus_dir, caplog):
    import logging

    _, src, cfg = corpus_dir
    (src / "empty.txt").write_text("   \n\n   ")   # parses to zero blocks -> zero chunks
    corpus = madosho.open(cfg)
    with caplog.at_level(logging.WARNING, logger="madosho.notes"):
        corpus.ingest()
    assert "0 chunks" in caplog.text


def test_ingest_file_returns_artifacts(corpus_dir):
    import hashlib
    import mimetypes
    from pathlib import Path

    from madosho.core.types import IngestArtifacts, SourceFile
    _, source, cfg = corpus_dir
    corpus = madosho.open(cfg)
    path = sorted(p for p in Path(source).rglob("*") if p.is_file())[0]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sf = SourceFile(path=str(path), content_hash=digest,
                    mimetype=mimetypes.guess_type(path)[0] or "application/octet-stream")

    artifacts = corpus.ingest_file(sf)

    assert isinstance(artifacts, IngestArtifacts)
    assert artifacts.doc_id          # the kernel document id, for server linkage
    assert artifacts.chunks          # at least one chunk on a non-empty file
    assert all(c.doc_id == artifacts.doc_id for c in artifacts.chunks)
    # blocks carry provenance (bbox slot reserved for L3); tables are a subset
    assert all(hasattr(b.provenance, "bbox") for b in artifacts.blocks)
