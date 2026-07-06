"""Open and cache the kernel Corpus bound to one pipeline's collection. Mirrors
corpus_cache but keyed by pipeline id + config hash, so each built pipeline serves
its own already-built index and a rebuilt pipeline reopens. Embedders/rerankers
sharing a model are loaded per process; scale by adding query replicas.

Deviation from corpus_cache: _open takes a raw config dict (not a pre-built
MadoshoConfig) so tests can patch the opener with a minimal/invalid config dict
without hitting MadoshoConfig validation. The production path builds MadoshoConfig
inside the default _open implementation."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from madosho.core.config import MadoshoConfig
from madosho.core.corpus import Corpus, open_corpus_from_config
from madosho_server import db


def _open(config: dict, data_dir: Path) -> Corpus:
    """Default opener: build MadoshoConfig then delegate to open_corpus_from_config.
    Indirection so tests patch this function to bypass model loading and MadoshoConfig
    validation (test pipelines carry minimal/invalid config dicts)."""
    cfg = MadoshoConfig(**config)
    return open_corpus_from_config(cfg, data_dir=data_dir)


# Maps pipeline_id -> (config_hash, opened Corpus). One entry per pipeline id;
# evicted and replaced whenever the config hash changes (rebuild, config change).
_CACHE: dict[int, tuple[str, Corpus]] = {}
_LOCK = threading.Lock()


def _config_hash(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode()
    ).hexdigest()


def corpus_for(pipeline_row: "db.Pipeline", corpora_dir: str) -> Corpus:
    """Return the opened (cached) Corpus for a pipeline. Thread-safe; reopens when
    the pipeline's config hash changes so a rebuild takes effect without a restart."""
    with _LOCK:
        h = _config_hash(pipeline_row.config)
        entry = _CACHE.get(pipeline_row.id)
        if entry is None or entry[0] != h:
            data_dir = Path(corpora_dir) / f"pipeline-{pipeline_row.id}"
            corpus = _open(pipeline_row.config, data_dir)
            _CACHE[pipeline_row.id] = (h, corpus)
        return _CACHE[pipeline_row.id][1]


def reset_cache() -> None:
    with _LOCK:
        _CACHE.clear()
