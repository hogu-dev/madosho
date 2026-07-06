# tests/unit/test_eval_attribute.py
"""Scan results -> 0-5 cells -> technique_rating(source=f-empirical).
Cells derive only from real whole-pipeline runs; bottleneck = most headroom."""
from madosho_server import db
from madosho_server.eval import attribute


def _scan(baseline_mrr, stage_best):
    return {"baseline": {"post": {"mrr": baseline_mrr}},
            "stages": {stage: [{"label": f"{stage} cand",
                                "stage": stage, "post": {"mrr": best}}]
                       for stage, best in stage_best.items()}}


def test_cell_drops_when_a_stage_has_headroom():
    # baseline 0.4; rerank can reach 0.6 (big headroom) -> lower cell than a stage
    # with no better candidate.
    cell_lots = attribute.headroom_to_cell(s0=0.4, best_stage=0.6)
    cell_none = attribute.headroom_to_cell(s0=0.4, best_stage=0.4)
    assert 0.0 <= cell_lots <= 5.0
    assert cell_lots < cell_none


def test_bottleneck_is_the_stage_with_most_headroom():
    scan = _scan(0.40, {"rerank": 0.60, "embed": 0.42, "semantic": 0.41})
    cells = attribute.cells_from_scan(scan)
    assert cells["bottleneck"] == "rerank"


def test_cells_from_scan_includes_a_suggestion_when_a_swap_helps():
    scan = _scan(0.40, {"rerank": 0.60})
    cells = attribute.cells_from_scan(scan)
    rr = cells["stages"]["rerank"]
    assert rr["suggestion"] and "rerank cand" in rr["suggestion"]
    assert rr["score"] == attribute.headroom_to_cell(0.40, 0.60)


def test_write_cube_persists_f_empirical_rows(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}); s.add(c); s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="running"); s.add(run); s.commit(); s.refresh(run)
        scan = _scan(0.40, {"rerank": 0.60, "embed": 0.42})
        attribute.write_cube(s, corpus_id=c.id, eval_run_id=run.id, scan=scan)
        s.commit()
        rows = s.query(db.TechniqueRating).filter_by(source="f-empirical").all()
        dims = {r.dimension for r in rows}
        assert dims == {"rerank", "embed"}
        assert all(r.rater_version == attribute.RATER_VERSION for r in rows)
        # cube cell links back to its run via candidate_config note
        assert all(str(run.id) in (r.candidate_config or "") for r in rows)


def test_write_cube_replaces_prior_f_empirical_rows(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'a2.db'}"); db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={"corpus": "c"}); s.add(c); s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="running"); s.add(run); s.commit(); s.refresh(run)
        scan = _scan(0.40, {"rerank": 0.60})
        attribute.write_cube(s, corpus_id=c.id, eval_run_id=run.id, scan=scan); s.commit()
        attribute.write_cube(s, corpus_id=c.id, eval_run_id=run.id, scan=scan); s.commit()
        n = s.query(db.TechniqueRating).filter_by(source="f-empirical", dimension="rerank").count()
        assert n == 1
