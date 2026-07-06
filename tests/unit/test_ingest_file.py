# tests/unit/test_ingest_file.py
import hashlib

from madosho.core.config import MadoshoConfig
from madosho.core.corpus import open_corpus_from_config
from madosho.core.types import SourceFile


def _corpus(tmp_path):
    cfg = MadoshoConfig(
        corpus="demo",
        ingest={"parser": "fake-parser", "chunker": "fake-chunker",
                "embedder": "hash-embedder", "store": "fake-store",
                "indexes": ["bm25", "dense"]},
        # fuse is required to move per-operator pools into ctx.hits (what
        # corpus.query() returns); keyword_search alone only fills ctx.pools.
        query=[{"keyword_search": {"k": 10}}, {"fuse": {"method": "rrf"}}],
    )
    return open_corpus_from_config(cfg, data_dir=tmp_path / "state")


def test_ingest_file_indexes_one_file(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("alpha beta gamma\n\ndelta epsilon")
    sf = SourceFile(path=str(f), mimetype="text/plain",
                    content_hash=hashlib.sha256(f.read_bytes()).hexdigest())

    corpus = _corpus(tmp_path)
    artifacts = corpus.ingest_file(sf)

    assert len(artifacts.chunks) == 2               # two paragraphs -> two chunks
    hits = corpus.query("alpha")
    assert any("alpha" in h.chunk.text for h in hits)
