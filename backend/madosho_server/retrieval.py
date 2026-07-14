"""Multi-index retrieval: a corpus query draws from each in-scope document's
effective pipeline index and merges by rank. One pipeline per document per
query, so no duplicate passages and no dedup step is needed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from madosho.core.errors import MadoshoError
from madosho.core.types import Hit
from madosho_server import db, membership
from madosho_server.pipelines import effective_pipeline

RRF_K = 60   # standard reciprocal-rank-fusion constant


@dataclass
class PipelineHit:
    """A kernel Hit plus which pipeline (and document) produced it, so citations
    can carry pipeline attribution (D14 stack addressing)."""
    hit: Hit
    pipeline_id: int
    pipeline_name: str
    document_id: int


def rrf_merge(ranked_lists, k: int = RRF_K, top_k: int | None = None):
    """Reciprocal-rank fusion across per-pipeline ranked lists. Different embedders
    live in different vector spaces, so raw scores are incomparable; RRF normalizes
    by rank. Keys by (pipeline_id, chunk_id) - hits from different pipelines are
    distinct chunks, so nothing collapses across documents."""
    scores: dict = {}
    for lst in ranked_lists:
        for rank, ph in enumerate(lst):
            key = (ph.pipeline_id, ph.hit.chunk_id)
            slot = scores.setdefault(key, [0.0, ph])
            slot[0] += 1.0 / (k + rank + 1)
    merged = sorted(scores.values(),
                    key=lambda sv: (-sv[0], sv[1].pipeline_id, sv[1].hit.chunk_id))
    out = [ph for _, ph in merged]
    return out[:top_k] if top_k is not None else out


def _pinned_pipeline(session, doc, pipeline_id):
    """The corpus's per-document pipeline pin, but only if it still points at one of
    the document's indexed pipelines. A stale/deleted/unbuilt pin returns None so the
    caller falls back to the document's default -- the pin is a preference, not a lock."""
    if pipeline_id is None:
        return None
    p = session.get(db.Pipeline, pipeline_id)
    if p is not None and p.document_id == doc.id and p.status == "indexed":
        return p
    return None


def _resolve(session, corpus_id: int, overrides: dict, *,
             include_generated: bool = True):
    """The pipelines to query for each in-scope (indexed) MEMBER document, flattened.
    Precedence per document: a request-time `overrides` pick (pipeline name -> Pipeline)
    wins; else this corpus's selected pipelines for the document (it may select SEVERAL,
    each queried and RRF-merged); else the document's default (effective) pipeline. A
    selected id that is stale/non-indexed is skipped, and a document whose selection ends
    up empty falls back to its default -- the selection is a preference, not a lock.
    include_generated=False drops alchemy-generated documents (work-unit exclusion,
    stage D) so a goal's runs never resolve their own prior drafts."""
    docs = membership.member_documents(session, corpus_id, indexed_only=True,
                                       include_generated=include_generated)
    override_by_doc = {p.document_id: p for p in overrides.values()}
    selections = membership.membership_selections(session, corpus_id)
    chosen = []
    for d in docs:
        if d.id in override_by_doc:
            chosen.append(override_by_doc[d.id])
            continue
        picked = [p for pid in selections.get(d.id, [])
                  if (p := _pinned_pipeline(session, d, pid)) is not None]
        if not picked:
            eff = effective_pipeline(session, d)
            if eff is not None:
                picked = [eff]
        chosen.extend(picked)
    return chosen


def multi_pipeline_query(session, corpus_row, text: str, *, open_pipeline,
                         pipeline_names=None, top_k: int | None = None,
                         include_generated: bool = True):
    """Resolve each document's effective pipeline (a named override wins), query
    each pipeline's own index through its operator stack, and RRF-merge the
    per-pipeline ranked lists. `open_pipeline(pipeline) -> kernel Corpus` is
    injected (prod: pipeline_cache.corpus_for; tests: a fake).
    include_generated=False drops alchemy-generated documents from the corpus
    scope (work-unit exclusion, stage D); see single_document_query for why the
    single-document path is left unfiltered."""
    member_ids = set(membership.member_document_ids(
        session, corpus_row.id, include_generated=include_generated))
    overrides: dict = {}
    for name in (pipeline_names or []):
        p = session.scalar(select(db.Pipeline).where(
            db.Pipeline.document_id.in_(member_ids), db.Pipeline.name == name,
            db.Pipeline.status == "indexed"))
        if p is None:
            raise MadoshoError(f"unknown or unbuilt pipeline '{name}'")
        overrides[name] = p

    pipelines = _resolve(session, corpus_row.id, overrides,
                         include_generated=include_generated)
    ranked_lists = []
    for p in pipelines:
        corpus = open_pipeline(p)
        hits = corpus.query(text)
        ranked_lists.append(
            [PipelineHit(h, p.id, p.name, p.document_id) for h in hits])

    if len(ranked_lists) == 1:                 # degenerate: that pipeline's stack output
        out = ranked_lists[0]
        return out[:top_k] if top_k is not None else out
    return rrf_merge(ranked_lists, top_k=top_k)


def single_document_query(session, document, text: str, *, open_pipeline,
                          pipeline_names=None, top_k: int | None = None):
    """Retrieve over ONE document (H11): its effective pipeline by default, or the
    named pipelines resolved within this document (names are unique per document,
    so a label is exact). Returns [] if the document has no indexed pipeline.

    Intentionally NOT filtered by include_generated (stage D): the generated-doc
    exclusion is a corpus-scope concept (a work unit fanning out over its corpus
    should not stumble onto its own prior draft). Asking for one document by id
    is an explicit request -- hiding it because it happens to be generated would
    be surprising, not helpful."""
    if pipeline_names:
        chosen = []
        for name in pipeline_names:
            p = session.scalar(select(db.Pipeline).where(
                db.Pipeline.document_id == document.id, db.Pipeline.name == name,
                db.Pipeline.status == "indexed"))
            if p is None:
                raise MadoshoError(f"unknown or unbuilt pipeline '{name}'")
            chosen.append(p)
    else:
        eff = effective_pipeline(session, document)
        chosen = [eff] if eff is not None else []

    ranked_lists = []
    for p in chosen:
        corpus = open_pipeline(p)
        hits = corpus.query(text)
        ranked_lists.append(
            [PipelineHit(h, p.id, p.name, p.document_id) for h in hits])

    if not ranked_lists:
        return []
    if len(ranked_lists) == 1:
        out = ranked_lists[0]
        return out[:top_k] if top_k is not None else out
    return rrf_merge(ranked_lists, top_k=top_k)
