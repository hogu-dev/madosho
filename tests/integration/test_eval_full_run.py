# tests/integration/test_eval_full_run.py
"""Full eval run wiring on fakes. A fake corpus ranks the answer chunk
high only for stronger configs, so the greedy search finds a real winner; the fake
opener builds ephemeral collections for ingest candidates so cleanup is asserted."""
from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, tasks
from madosho_server.settings import Settings


def _settings(tmp_path):
    return Settings(database_url="sqlite://", qdrant_url="http://q:6333",
                    filestore_dir=str(tmp_path / "fs"), corpora_dir=str(tmp_path / "co"))


def _rerank_top_k(config):
    for s in config.get("query", []):
        if isinstance(s, dict) and "rerank" in s:
            return s["rerank"].get("top_k", 8)
    return 8


class _FakeArtifacts:
    """Minimal artifact object returned by FakeApplyCorpus.ingest_file."""
    def __init__(self, doc_id: str):
        self.doc_id = doc_id

    def model_dump(self, *, mode: str = "python") -> dict:
        return {"chunks": [{"id": self.doc_id, "text": "fake"}]}


class FakeEvalCorpus:
    built: dict = {}     # collection -> indexed count (shared across opens within a run)

    def __init__(self, config, collection):
        self.config = config
        self.collection = collection

    def parse_file(self, sf):
        return ("parsed", sf.content_hash)

    def index_document(self, doc):
        FakeEvalCorpus.built[self.collection] = FakeEvalCorpus.built.get(self.collection, 0) + 1

    def ingest_file(self, sf, reporter=None):
        """Used when the eval runner indexes a candidate; returns a fake artifact bundle."""
        FakeEvalCorpus.built[self.collection] = FakeEvalCorpus.built.get(self.collection, 0) + 1
        return _FakeArtifacts(doc_id=f"fake-{sf.content_hash}")

    def query(self, text):
        good = _rerank_top_k(self.config) >= 12 or self.config["ingest"]["embedder"] == "alt-embed"
        # Text must match the seeded chunk text so scorer.is_relevant() can find it.
        ans = Chunk(id="k", doc_id="d",
                    text="The tenant must give ninety days written notice to vacate.",
                    position=0, page=1)
        noise = Chunk(id="n", doc_id="d", text="unrelated short", position=1, page=2)
        ordered = [ans, noise] if good else [noise, noise, ans]
        return [Hit(chunk_id=c.id, score=1.0, source_index="rrf", chunk=c) for c in ordered]


def _registry():
    return {"chunker": [], "reranker": [],
            "embedder": [{"name": "base-embed", "origin_tier": "us_src", "hardware": "cpu"},
                         {"name": "alt-embed", "origin_tier": "us_src", "hardware": "cpu"}]}


def _seed(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'run.db'}"); db.create_all()
    (tmp_path / "fs").mkdir(parents=True, exist_ok=True)
    cfg = {"corpus": "c",
           "ingest": {"parser": "p", "chunker": "ch", "embedder": "base-embed",
                      "store": {"qdrant": {"url": "http://q:6333"}}, "indexes": ["bm25", "dense"]},
           "query": ["keyword_search", "semantic_search", "fuse",
                     {"rerank": {"model": "rr", "top_k": 8}}]}
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config=cfg); s.add(c); s.commit(); s.refresh(c)
        for i in range(2):
            d = db.Document(filename=f"f{i}.pdf", content_hash=f"h{i}",
                            file_uri=f"h{i}/f.pdf", mimetype="application/pdf", status="indexed",
                            traits={"doc_type": "plain"},
                            artifacts={"chunks": [{"id": f"k{i}",
                                "text": "The tenant must give ninety days written notice to vacate."}]})
            s.add(d); s.flush(); membership.add_membership(s, d.id, c.id)
        s.commit(); s.refresh(c)
        run = db.EvalRun(corpus_id=c.id, status="pending",
                         sampling={"n_docs": 2, "questions_per_doc": 1}); s.add(run); s.commit()
        return c.id, run.id, cfg


def test_full_run_builds_cube_and_proposal_then_cleans_up(tmp_path, monkeypatch):
    FakeEvalCorpus.built = {}
    cid, rid, cfg = _seed(tmp_path)
    monkeypatch.setattr(tasks.FileStore, "path_for", lambda self, uri: tmp_path / "fs" / "f.pdf")
    (tmp_path / "fs" / "f.pdf").write_bytes(b"%PDF fake")
    dropped = []
    with db.SessionLocal() as s:
        tasks.execute_run(s, rid, _settings(tmp_path),
                          llm=lambda p: "What notice must the tenant give?",
                          opener=lambda c, coll: FakeEvalCorpus(c, coll),
                          list_registry=_registry,
                          drop_collection=lambda name: dropped.append(name))
        run = s.get(db.EvalRun, rid)
        assert run.status == "done"
        # cube backfilled with f-empirical rows
        assert s.query(db.TechniqueRating).filter_by(source="f-empirical").count() >= 1
        # a winning proposal exists (rerank top_k>=12 or alt-embed beat the baseline)
        prop = s.query(db.ConfigProposal).filter_by(corpus_id=cid, status="proposed").one()
        assert prop.evidence["projected"] > prop.evidence["baseline"]
        # ephemeral collection(s) built for the alt-embed candidate, then dropped (no leak)
        assert len(run.ephemeral_collections) >= 1
        assert sorted(dropped) == sorted(run.ephemeral_collections)
