from madosho.core.config import MadoshoConfig
from madosho_server.default_config import default_pipeline_config


def test_default_config_is_a_valid_kernel_config():
    cfg = default_pipeline_config("demo", "http://qdrant:6333")
    model = MadoshoConfig(**cfg)        # kernel validates it (no extras needed)

    assert model.corpus == "demo"
    assert model.source is None          # service feeds files one at a time
    assert model.ingest.store.name == "qdrant"
    assert model.ingest.store.options["url"] == "http://qdrant:6333"
    names = [step.name for step in model.query]
    assert names == ["keyword_search", "semantic_search", "fuse", "rerank"]
    rerank = model.query[-1]
    assert rerank.options["model"] == "granite-reranker-english-r2"
