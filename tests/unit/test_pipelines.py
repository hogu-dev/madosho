from madosho_server import db, pipelines


def _setup(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'pl.db'}"); db.create_all()
    s = db.SessionLocal()
    c = db.Corpus(name="c", config={"corpus": "c", "query": []})
    s.add(c); s.commit(); s.refresh(c)
    d = db.Document(filename="contract.pdf", content_hash="h",
                    file_uri="u", mimetype="application/pdf", status="indexed")
    s.add(d); s.commit(); s.refresh(d)
    return s, c, d


# artifacts shaped like Document.artifacts (chunks carry text + page)
def _artifacts(n_chunks, chars):
    return {"chunks": [{"id": f"k{i}", "text": "x" * chars, "page": 0, "position": i}
                       for i in range(n_chunks)], "blocks": []}


def test_default_pipeline_name_from_filename():
    assert pipelines.default_pipeline_name("contract.pdf") == "contract_docling"
    assert pipelines.default_pipeline_name("My Report v2.PDF") == "My_Report_v2_docling"
    assert pipelines.default_pipeline_name("/a/b/policy.pdf") == "policy_docling"


def test_slots_from_config_reads_tool_names():
    cfg = {"ingest": {"parser": "docling", "chunker": "docling-hybrid",
                      "embedder": {"granite-embedding-english-r2": {}}}}
    assert pipelines.slots_from_config(cfg) == {
        "extract": "docling", "chunk": "docling-hybrid",
        "index": "granite-embedding-english-r2"}


def test_rate_pipeline_steps_writes_named_rows_for_three_ingest_dims(tmp_path):
    s, c, d = _setup(tmp_path)
    p = db.Pipeline(document_id=d.id, name="contract_docling",
                    config={}, artifacts=_artifacts(6, 400), status="indexed")
    s.add(p); s.commit(); s.refresh(p)
    pipelines.rate_pipeline_steps(s, p); s.commit()
    rows = s.query(db.TechniqueRating).filter_by(candidate_config="contract_docling").all()
    dims = {r.dimension for r in rows}
    assert dims == {"extraction", "chunk", "embed"}        # only the ingest-side steps
    assert all(r.source == "static" for r in rows)


def test_rate_pipeline_steps_is_idempotent(tmp_path):
    s, c, d = _setup(tmp_path)
    p = db.Pipeline(document_id=d.id, name="p", config={},
                    artifacts=_artifacts(6, 400), status="indexed")
    s.add(p); s.commit(); s.refresh(p)
    pipelines.rate_pipeline_steps(s, p); s.commit()
    pipelines.rate_pipeline_steps(s, p); s.commit()       # re-rate
    rows = s.query(db.TechniqueRating).filter_by(candidate_config="p").all()
    assert len(rows) == 3                                 # not 6


def test_pipeline_rating_is_the_sum_of_step_rows(tmp_path):
    s, c, d = _setup(tmp_path)
    for dim, score in (("extraction", 4.0), ("chunk", 3.0), ("embed", 2.0)):
        s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension=dim,
                                 candidate_config="p1", score=score, source="static"))
    s.commit()
    assert pipelines.pipeline_rating(s, d.id, "p1") == 9.0


def test_pipeline_rating_picks_highest_precedence_per_dimension(tmp_path):
    s, c, d = _setup(tmp_path)
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="extraction",
                             candidate_config="p1", score=2.0, source="static"))
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="extraction",
                             candidate_config="p1", score=5.0, source="human"))
    s.commit()
    assert pipelines.pipeline_rating(s, d.id, "p1") == 5.0    # human outranks static


def test_effective_pipeline_prefers_highest_rated_indexed(tmp_path):
    s, c, d = _setup(tmp_path)
    lo = db.Pipeline(document_id=d.id, name="lo", config={}, status="indexed")
    hi = db.Pipeline(document_id=d.id, name="hi", config={}, status="indexed")
    building = db.Pipeline(document_id=d.id, name="wip", config={}, status="building")
    s.add_all([lo, hi, building]); s.commit()
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                             candidate_config="lo", score=2.0, source="static"))
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                             candidate_config="hi", score=4.0, source="static"))
    s.commit()
    assert pipelines.effective_pipeline(s, d).name == "hi"   # building one ignored


def test_effective_pipeline_honors_indexed_override(tmp_path):
    s, c, d = _setup(tmp_path)
    a = db.Pipeline(document_id=d.id, name="a", config={}, status="indexed")
    b = db.Pipeline(document_id=d.id, name="b", config={}, status="indexed")
    s.add_all([a, b]); s.commit(); s.refresh(b)
    d.selected_pipeline_id = b.id; s.commit()
    assert pipelines.effective_pipeline(s, d).name == "b"    # override wins over rating


def test_effective_pipeline_falls_back_when_override_not_indexed(tmp_path):
    s, c, d = _setup(tmp_path)
    a = db.Pipeline(document_id=d.id, name="a", config={}, status="indexed")
    wip = db.Pipeline(document_id=d.id, name="wip", config={}, status="building")
    s.add_all([a, wip]); s.commit(); s.refresh(wip)
    d.selected_pipeline_id = wip.id; s.commit()              # stale/unbuilt override
    assert pipelines.effective_pipeline(s, d).name == "a"    # ignore it, use highest-rated


def test_effective_pipeline_none_when_nothing_indexed(tmp_path):
    s, c, d = _setup(tmp_path)
    s.add(db.Pipeline(document_id=d.id, name="wip", config={}, status="building"))
    s.commit()
    assert pipelines.effective_pipeline(s, d) is None


def test_pipeline_step_ratings_picks_highest_precedence_per_dim(tmp_path):
    s, c, d = _setup(tmp_path)
    # two sources for the same dimension; higher precedence (measured) must win
    s.add_all([
        db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="extraction",
                           candidate_config="p1", score=3.0, source="static"),
        db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="extraction",
                           candidate_config="p1", score=4.0, source="measured"),
        db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="chunk",
                           candidate_config="p1", score=2.5, source="static"),
    ])
    s.commit()
    steps = pipelines.pipeline_step_ratings(s, d.id, "p1")
    assert steps == {"extraction": 4.0, "chunk": 2.5}
    # the summed rating still equals the sum of the picked per-step scores
    assert pipelines.pipeline_rating(s, d.id, "p1") == 6.5


def test_step_ratings_by_slot_maps_dimensions_to_slots(tmp_path):
    s, c, d = _setup(tmp_path)
    s.add_all([
        db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="extraction",
                           candidate_config="p1", score=3.0, source="static"),
        db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                           candidate_config="p1", score=2.0, source="static"),
    ])
    s.commit()
    assert pipelines.step_ratings_by_slot(s, d.id, "p1") == {"extract": 3.0, "index": 2.0}


def _idx_pipeline(s, c, d, name, slots):
    p = db.Pipeline(document_id=d.id, name=name, config={},
                    collection=name, status="indexed", slots=slots)
    s.add(p)
    return p


def _rate(s, c, d, name, dim, score, source="static"):
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension=dim,
                             candidate_config=name, score=score, source=source))


def test_recommended_pipeline_picks_best_tool_per_slot(tmp_path):
    s, c, d = _setup(tmp_path)
    _idx_pipeline(s, c, d, "p1", {"extract": "docling", "chunk": "hybrid", "index": "granite"})
    _idx_pipeline(s, c, d, "p2", {"extract": "pypdfium2", "chunk": "late", "index": "nomic"})
    s.commit()
    # extraction: p1 wins (4>3); chunk: p2 wins (3.5>2); embed: p2 wins (2.5>2)
    for name, dim, score in [("p1", "extraction", 4.0), ("p2", "extraction", 3.0),
                             ("p1", "chunk", 2.0), ("p2", "chunk", 3.5),
                             ("p1", "embed", 2.0), ("p2", "embed", 2.5)]:
        _rate(s, c, d, name, dim, score)
    s.commit()
    rec = pipelines.recommended_pipeline(s, d.id)
    assert rec is not None
    assert rec["slots"] == {"extract": "docling", "chunk": "late", "index": "nomic"}
    assert rec["steps"] == {"extract": 4.0, "chunk": 3.5, "index": 2.5}
    assert rec["projected_rating"] == 10.0
    assert rec["already_built"] is False
    assert rec["matches"] is None


def test_recommended_pipeline_flags_already_built_when_one_dominates(tmp_path):
    s, c, d = _setup(tmp_path)
    _idx_pipeline(s, c, d, "p1", {"extract": "docling", "chunk": "hybrid", "index": "granite"})
    _idx_pipeline(s, c, d, "p2", {"extract": "pypdfium2", "chunk": "late", "index": "nomic"})
    s.commit()
    # p1 wins every slot -> the best combo IS p1, which already exists
    for name, dim, score in [("p1", "extraction", 4.0), ("p2", "extraction", 3.0),
                             ("p1", "chunk", 4.0), ("p2", "chunk", 3.5),
                             ("p1", "embed", 4.0), ("p2", "embed", 2.5)]:
        _rate(s, c, d, name, dim, score)
    s.commit()
    rec = pipelines.recommended_pipeline(s, d.id)
    assert rec is not None
    assert rec["already_built"] is True
    assert rec["matches"] == "p1"


def test_recommended_pipeline_none_with_single_pipeline(tmp_path):
    s, c, d = _setup(tmp_path)
    _idx_pipeline(s, c, d, "p1", {"extract": "docling", "chunk": "hybrid", "index": "granite"})
    s.commit()
    for dim in ("extraction", "chunk", "embed"):
        _rate(s, c, d, "p1", dim, 3.0)
    s.commit()
    assert pipelines.recommended_pipeline(s, d.id) is None


def test_recommended_pipeline_none_when_a_slot_has_no_rating(tmp_path):
    s, c, d = _setup(tmp_path)
    _idx_pipeline(s, c, d, "p1", {"extract": "docling", "chunk": "hybrid", "index": "granite"})
    _idx_pipeline(s, c, d, "p2", {"extract": "pypdfium2", "chunk": "late", "index": "nomic"})
    s.commit()
    # only extraction + chunk are rated; the index slot has no scores anywhere
    for name in ("p1", "p2"):
        _rate(s, c, d, name, "extraction", 3.0)
        _rate(s, c, d, name, "chunk", 3.0)
    s.commit()
    assert pipelines.recommended_pipeline(s, d.id) is None
