# tests/unit/test_config_optional_source.py
from pathlib import Path

import yaml

from madosho.core.config import MadoshoConfig, load_config


def _ingest():
    return {"parser": "fake-parser", "chunker": "fake-chunker",
            "embedder": "hash-embedder", "store": "fake-store", "indexes": ["bm25", "dense"]}


def test_source_may_be_omitted():
    cfg = MadoshoConfig(corpus="demo", ingest=_ingest(), query=[])
    assert cfg.source is None


def test_source_still_accepted_and_expanded():
    cfg = MadoshoConfig(corpus="demo", source="~/docs", ingest=_ingest(), query=[])
    assert cfg.source == Path("~/docs").expanduser()


def test_load_config_without_source(tmp_path):
    cfg_path = tmp_path / "madosho.yaml"
    cfg_path.write_text(yaml.safe_dump(
        {"corpus": "demo", "ingest": _ingest(), "query": []}))
    cfg = load_config(cfg_path)
    assert cfg.source is None
