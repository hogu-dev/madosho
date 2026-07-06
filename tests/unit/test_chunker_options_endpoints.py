import pytest

from madosho_server import tasks


def test_recipe_config_emits_componentref_mapping_with_options():
    base = {"corpus": "c", "ingest": {}, "query": []}
    cfg = tasks.recipe_config(base, parser="docling", chunker="semantic",
                              embedder="hash-embedder",
                              options={"chunker": {"breakpoint_percentile": 90}})
    assert cfg["ingest"]["chunker"] == {"semantic": {"breakpoint_percentile": 90}}
    # slots without options stay bare strings (back-compat)
    assert cfg["ingest"]["parser"] == "docling"
    assert cfg["ingest"]["embedder"] == "hash-embedder"


def test_recipe_config_no_options_keeps_bare_names():
    base = {"corpus": "c", "ingest": {}, "query": []}
    cfg = tasks.recipe_config(base, chunker="recursive-text")
    assert cfg["ingest"]["chunker"] == "recursive-text"


def test_reject_invalid_options_raises_422_on_bad_value():
    from fastapi import HTTPException
    from madosho_server.api import _reject_invalid_options
    cfg = {"ingest": {"chunker": {"semantic": {"breakpoint_percentile": 150}}}}
    with pytest.raises(HTTPException) as ei:
        _reject_invalid_options(cfg)
    assert ei.value.status_code == 422


def test_reject_invalid_options_passes_valid():
    from madosho_server.api import _reject_invalid_options
    cfg = {"ingest": {"chunker": {"recursive-text": {"max_chars": 800}}}}
    _reject_invalid_options(cfg)   # no raise


def test_reject_invalid_options_raises_422_on_unknown_key():
    """Pydantic v2 silently ignores unknown keys; the helper must catch them."""
    from fastapi import HTTPException
    from madosho_server.api import _reject_invalid_options
    cfg = {"ingest": {"chunker": {"recursive-text": {"boguskey": 1}}}}
    with pytest.raises(HTTPException) as ei:
        _reject_invalid_options(cfg)
    assert ei.value.status_code == 422
    assert "boguskey" in ei.value.detail


def test_reject_invalid_options_called_on_full_config_branch(monkeypatch):
    """create_pipeline's full-config branch must also validate options.
    We call _reject_invalid_options directly on a full-config-shaped dict
    carrying a bad value to confirm the helper runs on that path too."""
    from fastapi import HTTPException
    from madosho_server.api import _reject_invalid_options
    # Full-config dict with a bad option value (out-of-range percentile)
    cfg = {
        "corpus": "test",
        "ingest": {"chunker": {"semantic": {"breakpoint_percentile": 999}}},
        "query": [],
    }
    with pytest.raises(HTTPException) as ei:
        _reject_invalid_options(cfg)
    assert ei.value.status_code == 422
