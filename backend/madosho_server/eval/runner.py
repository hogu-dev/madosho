# backend/madosho_server/eval/runner.py
"""Stage runner + reuse cache. Runs a candidate pipeline END TO END (rate whole
machines, never parts) but reuses expensive shared work:

  - Parsed documents are cached by content hash (extraction is not swept in v1, so
    parse runs exactly once per document for the whole run: OCR never twice).
  - A candidate that changes only query operators (keyword/semantic/rerank) shares
    the baseline collection: no re-index, just retrieve with new params.
  - A candidate that changes the chunker or embedder needs different chunks/vectors,
    so it builds an ephemeral collection keyed by the ingest-config prefix, indexing
    the cached parsed docs once; later candidates with the same prefix reuse it.

The opener is injectable (default open_corpus_from_config wrapped to set the store
collection) so unit tests avoid real models/Qdrant. drop_collection is injectable
so cleanup works for both Qdrant (native client) and the fake test store."""
from __future__ import annotations

import copy
import hashlib
import json

from pathlib import Path

from madosho.core.config import MadoshoConfig
from madosho.core.corpus import open_corpus_from_config
from madosho_server.eval import scorer

EPHEMERAL_PREFIX = "madosho_eval_"


def apply_candidate(baseline: dict, candidate: dict) -> dict:
    """Return a new full config with the candidate's single change applied."""
    cfg = copy.deepcopy(baseline)
    if candidate["kind"] == "ingest":
        cfg["ingest"][candidate["field"]] = candidate["ref"]
        return cfg
    # query-side: replace the matching op's options (ops may be bare strings)
    op, options = candidate["op"], candidate["options"]
    new_query = []
    for step in cfg["query"]:
        name = step if isinstance(step, str) else next(iter(step))
        if name == op:
            new_query.append({op: options})
        else:
            new_query.append(step)
    cfg["query"] = new_query
    return cfg


def strip_rerank(config: dict) -> dict:
    """A copy of config with any rerank step removed (for pre-rerank scoring)."""
    cfg = copy.deepcopy(config)
    cfg["query"] = [s for s in cfg["query"]
                    if (s if isinstance(s, str) else next(iter(s))) != "rerank"]
    return cfg


def ingest_prefix(config: dict) -> str:
    """Stable hash of the ingest section: the identity of a collection. Two configs
    with the same ingest produce identical chunks+vectors and can share a collection
    even if their query operators differ."""
    blob = json.dumps(config.get("ingest", {}), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _default_opener(corpora_dir: str, run_id: int):
    """Open a corpus from a config dict, pointing its qdrant store at `collection`."""
    def opener(config: dict, collection: str | None):
        cfg = copy.deepcopy(config)
        if collection is not None:
            store = cfg["ingest"].get("store", {})
            if isinstance(store, dict) and "qdrant" in store:
                store["qdrant"]["collection"] = collection
        mc = MadoshoConfig(**cfg)
        data_dir = Path(corpora_dir) / f"corpus-eval-{run_id}-{ingest_prefix(cfg)}"
        return open_corpus_from_config(mc, data_dir=data_dir)
    return opener


def _qdrant_dropper(corpora_dir: str, run_id: int, baseline: dict):
    """Drop an ephemeral collection via a bare Qdrant client built from the store
    config.  Deliberately does NOT open a full corpus: opening runs ensure_schema /
    dim-validation, which raises for an embedder-swap collection (different dims)
    and would leak the collection.  delete_collection is idempotent (ignores missing).

    corpora_dir and run_id are kept in the signature for caller compatibility
    (tasks.execute_run and sweep_leaked_collections pass them) but are not used."""
    store = (((baseline.get("ingest") or {}).get("store") or {}).get("qdrant") or {})

    def drop(collection: str):
        import os
        from qdrant_client import QdrantClient  # deferred: optional dependency
        if store.get("location"):
            client = QdrantClient(location=store["location"])
        elif store.get("path"):
            client = QdrantClient(path=store["path"])
        else:
            client = QdrantClient(
                url=store.get("url") or "http://localhost:6333",
                api_key=os.environ.get(store.get("api_key_env") or "QDRANT_API_KEY") or None,
            )
        client.delete_collection(collection)

    return drop


class StageRunner:
    def __init__(self, baseline: dict, run_id: int, corpora_dir: str,
                 parsed_docs: dict, *, opener=None, drop_collection=None):
        self.baseline = baseline
        self.run_id = run_id
        self.parsed_docs = parsed_docs           # {content_hash: kernel Document}
        self._baseline_prefix = ingest_prefix(baseline)
        self._opener = opener or _default_opener(corpora_dir, run_id)
        self._drop = drop_collection or _qdrant_dropper(corpora_dir, run_id, baseline)
        self._built: dict[str, object] = {}      # prefix -> opened corpus (ephemeral or baseline)
        self.ephemeral_collections: list[str] = []
        self._dropped: list[str] = []
        self._locked: list[dict] = []

    def lock(self, candidate: dict) -> None:
        self._locked.append(candidate)

    def _stacked_config(self, candidate: dict | None) -> dict:
        cfg = self.baseline
        for c in self._locked:
            cfg = apply_candidate(cfg, c)
        return apply_candidate(cfg, candidate) if candidate else cfg

    def _corpus_for(self, config: dict):
        prefix = ingest_prefix(config)
        if prefix in self._built:
            return self._built[prefix]
        if prefix == self._baseline_prefix:
            corpus = self._opener(config, None)            # reuse baseline collection
        else:
            collection = f"{EPHEMERAL_PREFIX}{self.run_id}_{prefix}"
            corpus = self._opener(config, collection)
            for doc in self.parsed_docs.values():          # build once: index cached parses
                corpus.index_document(doc)
            self.ephemeral_collections.append(collection)
        self._built[prefix] = corpus
        return corpus

    def _retrieve(self, config: dict, questions: list[dict]) -> list[list[dict]]:
        corpus = self._corpus_for(config)
        out = []
        for q in questions:
            hits = corpus.query(q["question"]) if "question" in q else corpus.query(
                q.get("source_chunk_text", ""))
            out.append([{"id": h.chunk_id, "text": h.chunk.text} for h in hits])
        return out

    def run_candidate(self, candidate: dict, questions: list[dict]) -> dict:
        """Run one candidate end to end; return pre/post-rerank metrics. Pre-rerank
        isolates the reranker's lift: same retrieval, with vs without the rerank op.
        Scores on top of any locked changes (stacking)."""
        config = self._stacked_config(candidate)
        post_hits = self._retrieve(config, questions)
        pre_hits = self._retrieve(strip_rerank(config), questions)
        return {"label": candidate.get("label", candidate["stage"]),
                "stage": candidate["stage"],
                "post": scorer.score_run(post_hits, questions),
                "pre": scorer.score_run(pre_hits, questions)}

    def run_baseline(self, questions: list[dict]) -> dict:
        config = self._stacked_config(None)
        post_hits = self._retrieve(config, questions)
        pre_hits = self._retrieve(strip_rerank(config), questions)
        return {"label": "baseline", "stage": "baseline",
                "post": scorer.score_run(post_hits, questions),
                "pre": scorer.score_run(pre_hits, questions)}

    def cleanup(self) -> None:
        for name in self.ephemeral_collections:
            try:
                self._drop(name)
                self._dropped.append(name)
            except Exception:
                pass     # leaked-collection sweep (Task 10) is the backstop
