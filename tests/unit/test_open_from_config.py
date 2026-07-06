from madosho.core.config import MadoshoConfig
from madosho.core.corpus import open_corpus_from_config


def _cfg():
    return MadoshoConfig(
        corpus="demo",
        ingest={"parser": "fake-parser", "chunker": "fake-chunker",
                "embedder": "hash-embedder", "store": "fake-store",
                "indexes": ["bm25", "dense"]},
        query=[],
    )


def test_open_from_in_memory_config(tmp_path):
    corpus = open_corpus_from_config(_cfg(), data_dir=tmp_path / "state")
    assert corpus.name == "demo"
    assert (tmp_path / "state").is_dir()   # data_dir created
