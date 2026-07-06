"""GET /documents/{id}/extract-divergence: N-way extract comparison across any
number of a document's pipelines, read from stored artifacts (never a re-parse).
Generalises the 2-way /pipeline-extract with a single "they don't all agree here"
highlight per column and no baseline."""
import procrastinate
import pytest
from fastapi.testclient import TestClient

from madosho_server import api, db, tasks


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'a.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    # in-memory queue so the lifespan's app.open() needs no Postgres
    tasks.use_connector(procrastinate.testing.InMemoryConnector())


def _blocks(*texts_by_page):
    return {"blocks": [{"kind": "text", "content": t, "provenance": {"page": pg}}
                       for pg, t in texts_by_page]}


def _doc_with_three(client, third_page1="the slow brown fox"):
    """A document with three indexed pipelines; the first two agree on page 1 and
    the third differs (by default)."""
    with db.SessionLocal() as s:
        d = db.Document(filename="x.pdf", content_hash="x", file_uri="u",
                        mimetype="application/pdf", status="indexed")
        s.add(d); s.commit(); s.refresh(d)
        a = db.Pipeline(document_id=d.id, name="docling", config={}, status="indexed",
                        artifacts=_blocks((1, "the quick brown fox")))
        b = db.Pipeline(document_id=d.id, name="ctx", config={}, status="indexed",
                        artifacts=_blocks((1, "the quick brown fox")))
        c = db.Pipeline(document_id=d.id, name="fast", config={}, status="indexed",
                        artifacts=_blocks((1, third_page1)))
        s.add_all([a, b, c]); s.commit()
        return d.id, [a.id, b.id, c.id]


def test_three_way_divergence_flags_the_odd_one_out(env):
    with TestClient(api.app) as client:
        did, ids = _doc_with_three(client)
        r = client.get(f"/documents/{did}/extract-divergence", params={"ids": ids})
        assert r.status_code == 200
        body = r.json()
        assert [p["id"] for p in body["pipelines"]] == ids
        assert [p["name"] for p in body["pipelines"]] == ["docling", "ctx", "fast"]
        page = body["pages"][0]
        assert page["page"] == 1
        cols = page["columns"]
        assert len(cols) == 3
        # the disagreeing locus is flagged in EVERY column (symmetric, no baseline)
        assert all(c["spans"] for c in cols)
        assert cols[0]["text"][cols[0]["spans"][0][0]:cols[0]["spans"][0][1]] == "quick"
        assert cols[2]["text"][cols[2]["spans"][0][0]:cols[2]["spans"][0][1]] == "slow"
        assert page["change"] > 0


def test_all_pipelines_identical_has_no_highlights(env):
    with TestClient(api.app) as client:
        did, ids = _doc_with_three(client, third_page1="the quick brown fox")
        r = client.get(f"/documents/{did}/extract-divergence", params={"ids": ids})
        assert r.status_code == 200
        page = r.json()["pages"][0]
        assert all(c["spans"] == [] for c in page["columns"])
        assert page["change"] == 0


def test_fewer_than_two_ids_is_400(env):
    with TestClient(api.app) as client:
        did, ids = _doc_with_three(client)
        r = client.get(f"/documents/{did}/extract-divergence", params={"ids": [ids[0]]})
        assert r.status_code == 400


def test_pipeline_not_on_this_document_is_404(env):
    with TestClient(api.app) as client:
        did, ids = _doc_with_three(client)
        r = client.get(f"/documents/{did}/extract-divergence",
                       params={"ids": [ids[0], 9999]})
        assert r.status_code == 404


def test_pipeline_without_artifacts_is_409(env):
    with TestClient(api.app) as client:
        did, ids = _doc_with_three(client)
        with db.SessionLocal() as s:
            building = db.Pipeline(document_id=did, name="pending", config={},
                                   status="building", artifacts=None)
            s.add(building); s.commit(); s.refresh(building)
            pid = building.id
        r = client.get(f"/documents/{did}/extract-divergence",
                       params={"ids": [ids[0], pid]})
        assert r.status_code == 409
