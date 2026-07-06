"""Pipeline naming, display slots, per-step rating writeback, summed rating, and
effective-pipeline resolution. The rating brain of the pipeline model: each
pipeline step is rated and a pipeline's rating is the SUM of its step ratings -
advice, never a verdict.
"""
from __future__ import annotations

import re

from sqlalchemy import delete, select

from madosho_server import db
from madosho_server.cube import _PRECEDENCE
from madosho_server.static_rater import rate_static
from madosho_server.traits import extract_traits

# The three ingest-side pipeline steps map onto the cube's existing dimensions
# (extract -> extraction, chunk -> chunk, index -> embed). The retrieval-side
# dimensions (keyword/semantic/rerank) stay corpus-level.
PIPELINE_STEP_DIMENSIONS = ("extraction", "chunk", "embed")

# The cube dimension each ingest step is rated under -> the display slot key the
# doc page renders it in (extract/chunk/index). One place owns the translation.
_SLOT_FOR_DIM = {"extraction": "extract", "chunk": "chunk", "embed": "index"}


def sanitize_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def default_pipeline_name(filename: str) -> str:
    """`contract.pdf` -> `contract_docling`. The doc name carries the pipeline by
    convention so names stay unique within a corpus."""
    base = filename.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] or "doc"
    return f"{sanitize_name(stem)}_docling"


def _ref_name(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return next(iter(v), None)
    return None


def slots_from_config(config: dict) -> dict:
    """Denormalized display: which tool fills each step. So `--list` and the doc
    page never parse the raw kernel config."""
    ing = config.get("ingest", {}) or {}
    return {"extract": _ref_name(ing.get("parser")),
            "chunk": _ref_name(ing.get("chunker")),
            "index": _ref_name(ing.get("embedder"))}


def rate_pipeline_steps(session, pipeline: "db.Pipeline") -> None:
    """Write per-step static ratings for one pipeline, keyed by
    candidate_config=pipeline.name, for the three ingest dimensions. Idempotent:
    clears this pipeline's prior static rows first. Caller commits."""
    if not pipeline.artifacts:
        return
    traits = extract_traits(pipeline.artifacts)
    session.execute(delete(db.TechniqueRating).where(
        db.TechniqueRating.document_id == pipeline.document_id,
        db.TechniqueRating.candidate_config == pipeline.name,
        db.TechniqueRating.source == "static"))
    for row in rate_static(traits):
        if row["dimension"] in PIPELINE_STEP_DIMENSIONS:
            session.add(db.TechniqueRating(
                document_id=pipeline.document_id,
                dimension=row["dimension"], candidate_config=pipeline.name,
                score=row["score"], source=row["source"], rationale=row["rationale"],
                suggestion=row["suggestion"], rater_version=row["rater_version"]))


def pipeline_step_ratings(session, document_id: int, name: str) -> dict[str, float]:
    """Per-step rating for one pipeline, keyed by cube dimension (extraction/chunk/
    embed). For each dimension, take the highest-precedence source's score
    (human > measured > f-empirical > static). Advice, not a verdict."""
    rows = session.scalars(select(db.TechniqueRating).where(
        db.TechniqueRating.document_id == document_id,
        db.TechniqueRating.candidate_config == name)).all()
    by_dim: dict[str, list] = {}
    for r in rows:
        by_dim.setdefault(r.dimension, []).append(r)
    return {dim: max(rs, key=lambda r: _PRECEDENCE.get(r.source, 0)).score
            for dim, rs in by_dim.items()}


def step_ratings_by_slot(session, document_id: int, name: str) -> dict[str, float]:
    """`pipeline_step_ratings` re-keyed by the doc page's slot names
    (extract/chunk/index), dropping any non-ingest dimension."""
    steps = pipeline_step_ratings(session, document_id, name)
    return {_SLOT_FOR_DIM[d]: s for d, s in steps.items() if d in _SLOT_FOR_DIM}


def pipeline_rating(session, document_id: int, name: str) -> float:
    """Sum of a pipeline's per-step ratings (see pipeline_step_ratings). Advice,
    never a verdict.

    Currently the only writer of candidate_config=name rows is rate_pipeline_steps
    (always source="static"), so the precedence pick is effectively a no-op today.
    It is kept so higher-precedence per-pipeline rows (human/measured/empirical)
    land cleanly if they are added later."""
    return round(sum(pipeline_step_ratings(session, document_id, name).values()), 2)


def document_pipelines(session, document_id: int, *, indexed_only: bool = False):
    q = select(db.Pipeline).where(db.Pipeline.document_id == document_id)
    if indexed_only:
        q = q.where(db.Pipeline.status == "indexed")
    return list(session.scalars(q.order_by(db.Pipeline.id)))


def effective_pipeline(session, document: "db.Document"):
    """The pipeline a document answers through by default: the saved UI override if
    it points at an indexed pipeline, else the highest-rated indexed pipeline.
    Deterministic tie-break: highest rating, then lowest pipeline id. None if no
    pipeline is indexed yet."""
    indexed = document_pipelines(session, document.id, indexed_only=True)
    if not indexed:
        return None
    if document.selected_pipeline_id is not None:
        chosen = next((p for p in indexed if p.id == document.selected_pipeline_id), None)
        if chosen is not None:
            return chosen
    return max(indexed, key=lambda p: (pipeline_rating(session, p.document_id, p.name), -p.id))


# The doc-page slot order the recommendation is assembled in.
_RECO_SLOTS = ("extract", "chunk", "index")


def recommended_pipeline(session, document_id: int):
    """The "recommended test": for each ingest slot, the tool with the highest
    per-step rating across this document's INDEXED pipelines, assembled into one
    candidate combo. D15 advice, never a verdict - summing step ratings ignores
    step interactions, so this is a combo worth TESTING, not a claim it is better.

    Returns None when there is nothing useful to suggest: fewer than 2 indexed
    pipelines (no alternative to compose from), or a slot with no rated tool
    anywhere (cannot form a full combo). Otherwise returns a dict with the winning
    slots/steps, the summed projected_rating, and whether that exact combo already
    exists as a pipeline (already_built / matches). Deterministic tie-break: higher
    rating, then lower pipeline id."""
    pipes = document_pipelines(session, document_id, indexed_only=True)
    if len(pipes) < 2:
        return None
    # slot -> (tool, rating, pipeline_id) of the current best seen
    best: dict[str, tuple[str, float, int]] = {}
    for p in pipes:
        steps = step_ratings_by_slot(session, document_id, p.name)
        slots = p.slots or {}
        for slot in _RECO_SLOTS:
            tool, rating = slots.get(slot), steps.get(slot)
            if tool is None or rating is None:
                continue
            cur = best.get(slot)
            if cur is None or rating > cur[1] or (rating == cur[1] and p.id < cur[2]):
                best[slot] = (tool, rating, p.id)
    if any(slot not in best for slot in _RECO_SLOTS):
        return None
    slots = {slot: best[slot][0] for slot in _RECO_SLOTS}
    steps = {slot: best[slot][1] for slot in _RECO_SLOTS}
    match = next((p.name for p in pipes
                  if {s: (p.slots or {}).get(s) for s in _RECO_SLOTS} == slots), None)
    return {"slots": slots, "steps": steps,
            "projected_rating": round(sum(steps.values()), 2),
            "already_built": match is not None, "matches": match}
