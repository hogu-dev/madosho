import pytest

pytest.importorskip("docling")
pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")
pytestmark = pytest.mark.slow

import madosho
from madosho.cli.main import main

from .conftest import make_pdf

CONFIG = """
corpus: contracts
source: {source}

ingest:
  parser: router
  chunker: docling-hybrid
  embedder: granite-embedding-english-r2
  store: lancedb
  indexes: [bm25, dense]

query:
  - keyword_search: {{k: 50}}
  - semantic_search: {{k: 50}}
  - fuse: {{method: rrf}}
  - rerank: {{model: granite-reranker-english-r2, top_k: 8}}
"""


@pytest.fixture
def project(tmp_path, monkeypatch, contract_pdf):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "pdfs"
    src.mkdir()
    (src / "contract_a.pdf").write_bytes(contract_pdf.read_bytes())
    make_pdf(src / "memo_b.pdf", title="Office Memo", paragraphs=[
        "The cafeteria reopens on Monday.",
        "Parking passes renew quarterly.",
    ])
    (tmp_path / "madosho.yaml").write_text(CONFIG.format(source=src))
    return tmp_path


def test_milestone_ingest_query_cited_chunks(project):
    corpus = madosho.open("madosho.yaml")
    report = corpus.ingest()
    assert report.processed == 2 and report.failed == 0

    hits = corpus.query("What does the termination clause require?")
    assert hits, "hybrid+rerank pipeline returned nothing"
    top = hits[0]
    assert "ninety days" in top.text
    assert "contract_a.pdf" in top.citation and "p." in top.citation

    # idempotent re-ingest (content-hash skip)
    again = madosho.open("madosho.yaml").ingest()
    assert again.processed == 0 and again.skipped == 2


def test_milestone_via_cli(project, capsys):
    assert main(["ingest"]) == 0
    capsys.readouterr()
    assert main(["query", "What does the termination clause require?"]) == 0
    out = capsys.readouterr().out
    assert "ninety days" in out and "contract_a.pdf" in out
