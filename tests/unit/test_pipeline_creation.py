from pathlib import Path
from types import SimpleNamespace
from madosho_server import tasks, db, pipelines as pipelines_mod


def test_pipeline_collection_is_corpus_free():
    assert tasks._pipeline_collection(7) == "madosho_p7"


def test_pipeline_data_dir_is_corpus_free(tmp_path):
    assert tasks._pipeline_data_dir(str(tmp_path), 7) == Path(tmp_path) / "pipeline-7"


def _doc_for(tmp_path, name="contract.pdf"):
    db.configure_engine(f"sqlite:///{tmp_path/'t.db'}"); db.create_all()
    s = db.SessionLocal()
    d = db.Document(filename=name, content_hash=name, file_uri="u",
                    mimetype="application/pdf", status="received")
    s.add(d); s.commit(); s.refresh(d)
    return s, d


_BASE = {
    "corpus": "library",
    "ingest": {"parser": "docling", "chunker": "docling-hybrid",
               "embedder": "granite-embedding-english-r2",
               "store": {"qdrant": {"url": "http://q", "collection": "stale"}},
               "indexes": ["bm25", "dense"]},
    "query": ["keyword_search", "semantic_search", "fuse",
              {"rerank": {"model": "granite-reranker-english-r2"}}],
}


def test_recipe_config_overrides_only_given_slots_and_strips_collection():
    cfg = tasks.recipe_config(_BASE, parser="pypdfium2")
    assert cfg["ingest"]["parser"] == "pypdfium2"
    assert cfg["ingest"]["chunker"] == "docling-hybrid"        # untouched
    assert cfg["ingest"]["embedder"] == "granite-embedding-english-r2"
    assert "collection" not in cfg["ingest"]["store"]["qdrant"]  # stamped per-pipeline
    assert cfg["query"] == _BASE["query"]                      # query stack untouched
    assert _BASE["ingest"]["parser"] == "docling"             # base not mutated


def test_create_pipeline_from_config_is_find_or_create_by_name(tmp_path):
    s, d = _doc_for(tmp_path)
    cfg = tasks.recipe_config(_BASE, parser="pypdfium2")
    p1 = tasks.create_pipeline_from_config(s, d, cfg, "contract_alt"); s.commit()
    assert p1.collection == f"madosho_p{p1.id}"
    assert p1.slots == {"extract": "pypdfium2", "chunk": "docling-hybrid",
                        "index": "granite-embedding-english-r2"}
    # same name -> the SAME pipeline back (slots never compared)
    p2 = tasks.create_pipeline_from_config(
        s, d, tasks.recipe_config(_BASE, parser="docling"), "contract_alt")
    assert p2.id == p1.id
    assert s.query(db.Pipeline).filter_by(document_id=d.id).count() == 1


def test_create_default_pipeline_still_works_via_wrapper(tmp_path):
    s, d = _doc_for(tmp_path)
    corpus = db.Corpus(name="c", config=_BASE); s.add(corpus); s.commit(); s.refresh(corpus)
    p = tasks.create_default_pipeline(s, corpus, d); s.commit()
    assert p.is_default is True
    assert p.name == pipelines_mod.default_pipeline_name("contract.pdf")
    assert p.collection == f"madosho_p{p.id}"


def test_eval_samples_only_member_documents(tmp_path, monkeypatch):
    """execute_run gathers the documents to evaluate through the
    document_corpus join (membership.member_documents), so an eval over one corpus
    never pulls in a document that belongs only to another corpus. We stub the golden
    step to capture the sampled docs and return [] (short-circuits before any qdrant/
    model work), then assert only the member doc was sampled."""
    db.configure_engine(f"sqlite:///{tmp_path/'e.db'}"); db.create_all()
    with db.SessionLocal() as s:
        a = db.Corpus(name="alpha", config=_BASE); b = db.Corpus(name="beta", config=_BASE)
        s.add_all([a, b]); s.commit(); s.refresh(a); s.refresh(b)
        mine = db.Document(filename="mine.pdf", content_hash="mine", file_uri="u1",
                           mimetype="application/pdf", status="indexed")
        other = db.Document(filename="other.pdf", content_hash="other", file_uri="u2",
                            mimetype="application/pdf", status="indexed")
        s.add_all([mine, other]); s.commit(); s.refresh(mine); s.refresh(other)
        s.add(db.DocumentCorpus(document_id=mine.id, corpus_id=a.id))     # member of alpha
        s.add(db.DocumentCorpus(document_id=other.id, corpus_id=b.id))    # member of beta only
        run = db.EvalRun(corpus_id=a.id, status="pending", sampling={})
        s.add(run); s.commit(); s.refresh(run)
        mine_id, run_id = mine.id, run.id

    seen = {}
    def fake_golden(doc_payloads, **kw):
        seen["ids"] = [d["id"] for d in doc_payloads]
        return []                                  # no questions -> execute_run stops early
    monkeypatch.setattr(tasks.golden, "build_golden_set", fake_golden)

    settings = SimpleNamespace(corpora_dir=str(tmp_path / "co"), filestore_dir=str(tmp_path / "fs"))
    with db.SessionLocal() as s:
        tasks.execute_run(s, run_id, settings, llm=SimpleNamespace(tokens=0),
                          opener=lambda *a, **k: None, list_registry=lambda: [],
                          drop_collection=lambda *a, **k: None)

    assert seen["ids"] == [mine_id]                # beta's doc excluded; only alpha's member sampled
