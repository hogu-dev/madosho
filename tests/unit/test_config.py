import pytest

from madosho.core.config import ComponentRef, MadoshoConfig, load_config
from madosho.core.errors import ConfigError

GOOD = """
corpus: contracts
source: ./docs/contracts
ingest:
  parser: router
  chunker: docling-hybrid
  embedder: granite-embedding-english-r2
  store: lancedb
  indexes: [bm25, dense]
query:
  - keyword_search: {k: 50}
  - semantic_search: {k: 50}
  - fuse: {method: rrf}
  - rerank: {model: granite-reranker-english-r2, top_k: 8}
"""


def write(tmp_path, text):
    p = tmp_path / "madosho.yaml"
    p.write_text(text)
    return p


def test_loads_spec_example(tmp_path):
    cfg = load_config(write(tmp_path, GOOD))
    assert cfg.corpus == "contracts"
    assert cfg.ingest.parser == ComponentRef(name="router")
    assert cfg.ingest.indexes == ["bm25", "dense"]
    assert cfg.query[0] == ComponentRef(name="keyword_search", options={"k": 50})
    assert cfg.query[3].options["model"] == "granite-reranker-english-r2"


def test_ingest_slot_accepts_options_mapping(tmp_path):
    cfg = load_config(write(tmp_path, GOOD.replace(
        "parser: router",
        "parser: {router: {fast_lane: true}}")))
    assert cfg.ingest.parser == ComponentRef(name="router", options={"fast_lane": True})


def test_missing_section_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="ingest"):
        load_config(write(tmp_path, "corpus: c\nsource: .\nquery: []\n"))


def test_multi_key_step_is_config_error(tmp_path):
    bad = GOOD.replace("- fuse: {method: rrf}", "- fuse: {method: rrf}\n    extra_key: 1")
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(write(tmp_path, bad))


def test_unknown_top_level_key_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="policy"):
        load_config(write(tmp_path, GOOD + "\npolicy:\n  licenses: [MIT]\n"))


def test_relative_source_is_anchored_to_config_dir(tmp_path):
    cfg = load_config(write(tmp_path, GOOD))      # source: ./docs/contracts
    assert cfg.source == tmp_path / "docs" / "contracts"


def test_absolute_source_is_left_alone(tmp_path):
    cfg = load_config(write(tmp_path, GOOD.replace("./docs/contracts", "/srv/contracts")))
    assert str(cfg.source) == "/srv/contracts"


def test_source_tilde_is_expanded(tmp_path):
    cfg = load_config(write(tmp_path, GOOD.replace("./docs/contracts", "~/contracts")))
    assert not str(cfg.source).startswith("~")


def test_corpus_name_must_be_path_safe(tmp_path):
    with pytest.raises(ConfigError, match="corpus"):
        load_config(write(tmp_path, GOOD.replace("corpus: contracts", "corpus: ../evil")))


def test_incompatible_parser_chunker_rejected(tmp_path):
    # pymupdf parser cannot feed the docling-hybrid chunker (no native object).
    # The kernel rejects it at config-validation time, not mid-build.
    bad = GOOD.replace("parser: router", "parser: pymupdf")
    with pytest.raises(ConfigError, match="docling-hybrid|incompatible|parser"):
        load_config(write(tmp_path, bad))


def test_compatible_recipe_still_loads(tmp_path):
    # swapping in recursive-text (no native requirement) is fine with any parser
    ok = GOOD.replace("parser: router", "parser: pymupdf").replace(
        "chunker: docling-hybrid", "chunker: recursive-text")
    cfg = load_config(write(tmp_path, ok))
    assert cfg.ingest.chunker.name == "recursive-text"
