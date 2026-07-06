"""GET /documents/{id}/pipeline-extract: extract-stage diff between two of a
document's pipelines, read from each pipeline's stored artifacts (never a re-parse).
Replaces the retired on-demand docling-vs-pypdfium2 extractor head-to-head."""
import pytest
from fastapi.testclient import TestClient

from madosho_server import api, db


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'a.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def _blocks(*texts_by_page):
    """texts_by_page = [(page, content), ...] -> docling-shaped artifacts blocks."""
    return {"blocks": [{"kind": "text", "content": t, "provenance": {"page": pg}}
                       for pg, t in texts_by_page]}


def _doc_with_pipelines(client):
    """A document with two indexed pipelines whose page-1 extractions differ."""
    with db.SessionLocal() as s:
        d = db.Document(filename="x.pdf", content_hash="x", file_uri="u",
                        mimetype="application/pdf", status="indexed")
        s.add(d); s.commit(); s.refresh(d)
        p_left = db.Pipeline(document_id=d.id, name="x_docling", config={},
                             status="indexed", artifacts=_blocks((1, "the quick fox")))
        p_right = db.Pipeline(document_id=d.id, name="x_fast", config={},
                              status="indexed", artifacts=_blocks((1, "the slow fox")))
        s.add(p_left); s.add(p_right); s.commit()
        return d.id, p_left.id, p_right.id


def test_diffs_two_pipelines_extract_from_stored_artifacts(env):
    with TestClient(api.app) as client:
        did, left, right = _doc_with_pipelines(client)
        r = client.get(f"/documents/{did}/pipeline-extract",
                       params={"left": left, "right": right})
        assert r.status_code == 200
        body = r.json()
        assert body["engine_a"] == "x_docling" and body["engine_b"] == "x_fast"
        assert body["pages"][0]["page"] == 1
        assert body["pages"][0]["text_a"] == "the quick fox"
        assert body["pages"][0]["text_b"] == "the slow fox"
        # "quick" vs "slow" differs -> non-zero change drives the page rail bars
        assert body["pages"][0]["change"] > 0


def test_pipeline_not_on_this_document_is_404(env):
    with TestClient(api.app) as client:
        did, left, right = _doc_with_pipelines(client)
        r = client.get(f"/documents/{did}/pipeline-extract",
                       params={"left": left, "right": 9999})
        assert r.status_code == 404


def test_pipeline_without_artifacts_is_409(env):
    with TestClient(api.app) as client:
        did, left, _ = _doc_with_pipelines(client)
        with db.SessionLocal() as s:
            building = db.Pipeline(document_id=did, name="x_pending", config={},
                                   status="building", artifacts=None)
            s.add(building); s.commit(); s.refresh(building)
            pid = building.id
        r = client.get(f"/documents/{did}/pipeline-extract",
                       params={"left": left, "right": pid})
        assert r.status_code == 409
