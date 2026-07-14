import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A bare in-memory "sqlite://" URL hands each connection its own private
    # :memory: database once the request is served off a different thread
    # (FastAPI runs sync endpoints via a threadpool) - a real file avoids that,
    # matching the pattern already used by the other TestClient-driven tests.
    db_url = f"sqlite:///{tmp_path / 'kb.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("KB_DIR", str(tmp_path / "kbs"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "0")
    from madosho_server import db
    from madosho_server.api import app
    db.configure_engine(db_url)
    db.create_all()
    return TestClient(app)


def _corpus(client, name="c1"):
    return client.post("/corpora", json={"name": name}).json()["id"]


def test_create_list_get_delete_kb(client):
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/kbs", json={"name": "My Notes"})
    assert r.status_code == 201
    kb = r.json()
    assert kb["name"] == "My Notes" and kb["slug"] == "my-notes"
    assert kb["corpus_id"] == cid and kb["corpus_name"] == "c1"

    listed = client.get("/kbs").json()
    assert [k["id"] for k in listed] == [kb["id"]]

    detail = client.get(f"/kbs/{kb['id']}").json()
    assert detail["pages"] == [] and detail["index_markdown"].startswith("# Index")

    assert client.delete(f"/kbs/{kb['id']}").status_code == 204
    assert client.get("/kbs").json() == []


def test_create_kb_duplicate_name_409(client):
    cid = _corpus(client)
    client.post(f"/corpora/{cid}/kbs", json={"name": "Notes"})
    r = client.post(f"/corpora/{cid}/kbs", json={"name": "Notes"})
    assert r.status_code == 409


def test_create_kb_missing_corpus_404(client):
    r = client.post("/corpora/999/kbs", json={"name": "Notes"})
    assert r.status_code == 404


def test_get_missing_kb_404(client):
    assert client.get("/kbs/999").status_code == 404
