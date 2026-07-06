from madosho_server import db, pipeline_cache


def _pipeline(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'pc.db'}"); db.create_all()
    s = db.SessionLocal()
    c = db.Corpus(name="c", config={"corpus": "c", "query": []})
    s.add(c); s.commit(); s.refresh(c)
    d = db.Document(filename="a.pdf", content_hash="h",
                    file_uri="u", mimetype="application/pdf")
    s.add(d); s.commit(); s.refresh(d)
    p = db.Pipeline(document_id=d.id, name="a_docling",
                    config={"corpus": "c", "ingest": {}, "query": []},
                    collection="madosho_c_1", status="indexed")
    s.add(p); s.commit(); s.refresh(p)
    return p


def test_opens_once_then_caches(tmp_path, monkeypatch):
    pipeline_cache.reset_cache()
    p = _pipeline(tmp_path)
    calls = []
    monkeypatch.setattr(pipeline_cache, "_open",
                        lambda cfg, data_dir: calls.append((cfg, data_dir)) or object())
    a = pipeline_cache.corpus_for(p, str(tmp_path))
    b = pipeline_cache.corpus_for(p, str(tmp_path))
    assert a is b
    assert len(calls) == 1                          # opened once, cached after


def test_reopens_when_config_changes(tmp_path, monkeypatch):
    pipeline_cache.reset_cache()
    p = _pipeline(tmp_path)
    monkeypatch.setattr(pipeline_cache, "_open", lambda cfg, data_dir: object())
    a = pipeline_cache.corpus_for(p, str(tmp_path))
    p.config = {"corpus": "c", "ingest": {"chunker": "fixed"}, "query": []}
    b = pipeline_cache.corpus_for(p, str(tmp_path))
    assert a is not b                               # config hash changed -> reopen


def test_data_dir_is_per_pipeline(tmp_path, monkeypatch):
    pipeline_cache.reset_cache()
    p = _pipeline(tmp_path)
    seen = {}
    monkeypatch.setattr(pipeline_cache, "_open",
                        lambda cfg, data_dir: seen.setdefault("dir", data_dir) or object())
    pipeline_cache.corpus_for(p, str(tmp_path))
    assert seen["dir"].as_posix().endswith(f"pipeline-{p.id}")
