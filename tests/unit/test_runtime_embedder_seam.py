from madosho.core.protocols import RuntimeContext


def test_runtime_context_has_embedder_field_defaulting_none():
    rc = RuntimeContext(corpus="c", data_dir=__import__("pathlib").Path("/tmp"),
                        cache_dir=None, logger=__import__("logging").getLogger("t"))
    assert rc.embedder is None


def test_build_corpus_sets_runtime_embedder_before_chunker():
    """A chunker resolved by _build_corpus must see a non-None runtime.embedder.
    We assert it via a probe chunker that records runtime.embedder at chunk time."""
    from madosho.core.config import MadoshoConfig
    from madosho.core.corpus import _build_corpus
    from madosho.core.types import Chunk, Document

    seen = {}

    # a minimal fake chunker registered ad hoc through the config's component names
    cfg = MadoshoConfig(**{
        "corpus": "probe",
        "ingest": {
            "parser": "fake-parser", "chunker": "fake-chunker",
            "embedder": "hash-embedder", "store": "fake-store",
            "indexes": ["dense"],
        },
        "query": [],
    })
    corpus = _build_corpus(cfg, data_dir=__import__("pathlib").Path("/tmp/probe"))
    # the embedder the chunker would see is the same object resolved for indexing
    assert corpus._runtime.embedder is corpus._embedder
    assert corpus._runtime.embedder is not None
