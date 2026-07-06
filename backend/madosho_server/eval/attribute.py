# backend/madosho_server/eval/attribute.py
"""Turn scan results into measured cube cells. The cube (E) already renders
source=f-empirical above static and below measured/human; F just writes the rows.

Cell philosophy (fixed): every measured cell derives from real whole-pipeline runs.
Mapping (constants tunable): a stage scores high when the pipeline already retrieves
well AND no candidate for this stage beats the current one. We use
    cell = clamp(5 * S0 * (S0 / best_stage), 0, 5)
where S0 is the baseline primary metric and best_stage the best candidate metric
for that stage. Alternative considered: map raw lift directly to a penalty; rejected
as harder to read (a great pipeline with a slightly-better candidate would score
mid). Bottleneck = stage with the largest lift (the swap that helps most)."""
from __future__ import annotations

from sqlalchemy import delete

from madosho_server import db

PRIMARY = "mrr"
SCALE = 5.0
RATER_VERSION = "f-empirical-v1"
# map F's swept stages to cube dimensions (extraction stays E's)
STAGE_TO_DIM = {"chunk": "chunk", "embed": "embed", "keyword": "keyword",
                "semantic": "semantic", "rerank": "rerank"}


def headroom_to_cell(s0: float, best_stage: float) -> float:
    ratio = (s0 / best_stage) if best_stage > 0 else 1.0
    return round(max(0.0, min(SCALE, SCALE * s0 * ratio)), 1)


def cells_from_scan(scan: dict) -> dict:
    """Pure: scan -> {stages: {stage: {score, lift, suggestion, best_label}}, bottleneck}."""
    s0 = scan["baseline"]["post"][PRIMARY]
    stages = {}
    best_lift = -1.0
    bottleneck = None
    for stage, results in scan["stages"].items():
        if not results:
            continue
        best = max(results, key=lambda r: r["post"][PRIMARY])
        best_metric = best["post"][PRIMARY]
        lift = best_metric - s0
        suggestion = (f"Swap helps: {best['label']} (+{round(lift, 3)} {PRIMARY})"
                      if lift > 0 else None)
        stages[stage] = {"score": headroom_to_cell(s0, best_metric),
                         "lift": round(lift, 4), "best_label": best["label"],
                         "suggestion": suggestion}
        if lift > best_lift:
            best_lift, bottleneck = lift, stage
    return {"baseline": s0, "stages": stages, "bottleneck": bottleneck}


def write_cube(session, corpus_id: int, eval_run_id: int, scan: dict) -> dict:
    """Persist f-empirical rows for each swept stage. Corpus-level rows
    (document_id=None) since F rates the whole pipeline, not per document.
    Idempotent: clears this corpus's prior f-empirical rows first."""
    cells = cells_from_scan(scan)
    session.execute(delete(db.TechniqueRating).where(
        db.TechniqueRating.corpus_id == corpus_id,
        db.TechniqueRating.source == "f-empirical"))
    for stage, cell in cells["stages"].items():
        rationale = (f"Measured {PRIMARY}={cells['baseline']:.3f} baseline; "
                     f"best candidate lift {cell['lift']:+.3f}.")
        session.add(db.TechniqueRating(
            corpus_id=corpus_id, document_id=None, dimension=STAGE_TO_DIM[stage],
            candidate_config=f"eval-run:{eval_run_id}", score=cell["score"],
            source="f-empirical", rationale=rationale, suggestion=cell["suggestion"],
            rater_version=RATER_VERSION))
    return cells
