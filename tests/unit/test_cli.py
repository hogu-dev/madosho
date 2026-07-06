import pytest

from madosho.cli.main import main

from .test_corpus import CONFIG  # reuse the fakes-based config template


LANCE_CONFIG = """
corpus: notes
source: {source}
ingest:
  parser: fake-parser
  chunker: fake-chunker
  embedder: hash-embedder
  store: lancedb
  indexes: [bm25, dense]
query:
  - keyword_search: {{k: 10}}
  - semantic_search: {{k: 10}}
  - fuse: {{method: rrf}}
  - rerank: {{model: fake-reranker, top_k: 2}}
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("The termination clause requires ninety days notice.")
    (tmp_path / "madosho.yaml").write_text(CONFIG.format(source=src))
    return tmp_path


def test_ingest_then_query(tmp_path, monkeypatch, capsys):
    # in-memory fakes can't persist across two main() invocations, so the
    # round-trip test runs on the real embedded store (plan-bug fix)
    pytest.importorskip("lancedb")
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("The termination clause requires ninety days notice.")
    (tmp_path / "madosho.yaml").write_text(LANCE_CONFIG.format(source=src))

    assert main(["ingest"]) == 0
    out = capsys.readouterr().out
    assert "processed: 1" in out

    assert main(["query", "termination clause notice"]) == 0
    out = capsys.readouterr().out
    assert "ninety days" in out and "a.txt" in out


def test_components_list_shows_meta_columns(project, capsys):
    assert main(["components", "list"]) == 0
    out = capsys.readouterr().out
    # real components + the metadata columns render...
    assert "keyword_search" in out and "Apache-2.0" in out and "store" in out
    # ...but the hidden in-memory testing fakes stay out of the default listing
    # (they mirror the web /components form, which also filters hidden specs).
    assert "fake-store" not in out and "hash-embedder" not in out


def test_components_list_all_surfaces_hidden_fakes(project, capsys):
    assert main(["components", "list", "--all"]) == 0
    out = capsys.readouterr().out
    for fake in ("fake-parser", "fake-chunker", "hash-embedder",
                 "fake-store", "fake-reranker"):
        assert fake in out


def test_config_error_is_friendly_not_traceback(project, capsys):
    (project / "madosho.yaml").write_text("corpus: x\nsource: .\nquery: []\n")
    assert main(["ingest"]) == 1
    assert "ingest" in capsys.readouterr().err
