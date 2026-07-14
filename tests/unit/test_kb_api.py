import io
import zipfile

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


def _kb(client, cid, name="KB"):
    return client.post(f"/corpora/{cid}/kbs", json={"name": name}).json()["id"]


def test_add_get_edit_page(client):
    cid = _corpus(client)
    kid = _kb(client, cid)
    r = client.post(f"/kbs/{kid}/pages", json={
        "type": "concept", "title": "Reranking", "description": "reorder",
        "tags": ["ir"], "sources": ["doc:3"], "body": "cross encoder"})
    assert r.status_code == 201
    page = r.json()
    assert page["slug"] == "reranking" and page["body"] == "cross encoder"

    got = client.get(f"/kbs/{kid}/pages/reranking").json()
    assert got["title"] == "Reranking" and got["tags"] == ["ir"]

    up = client.put(f"/kbs/{kid}/pages/reranking",
                    json={"description": "reorder hits", "body": "bi+cross"})
    assert up.status_code == 200 and up.json()["description"] == "reorder hits"
    assert client.get(f"/kbs/{kid}/pages/reranking").json()["body"] == "bi+cross"


def test_get_page_traversal_slug_rejected(client):
    cid = _corpus(client)
    kid = _kb(client, cid)
    client.post(f"/kbs/{kid}/pages", json={
        "type": "concept", "title": "Reranking", "description": "d",
        "body": "cross encoder"})
    # %2e%2e%2f decodes to "../" - the route still gets a raw "../" component
    # once the client/server decode the path, so this exercises the same
    # containment guard as a literal "../" would.
    r = client.get(f"/kbs/{kid}/pages/%2e%2e%2fsecret")
    assert r.status_code in (404, 422)
    # sanity: a normal missing slug still 404s (store-level guarantee is the
    # real backstop; this is best-effort defense-in-depth at the API layer)
    assert client.get(f"/kbs/{kid}/pages/nope").status_code == 404


def test_add_page_bad_type_422_and_missing_page_404(client):
    cid = _corpus(client)
    kid = _kb(client, cid)
    r = client.post(f"/kbs/{kid}/pages",
                    json={"type": "bogus", "title": "X", "description": "d"})
    assert r.status_code == 422
    assert client.get(f"/kbs/{kid}/pages/nope").status_code == 404


def test_add_duplicate_page_409(client):
    cid = _corpus(client)
    kid = _kb(client, cid)
    body = {"type": "concept", "title": "Chunking", "description": "d"}
    assert client.post(f"/kbs/{kid}/pages", json=body).status_code == 201
    assert client.post(f"/kbs/{kid}/pages", json=body).status_code == 409


def test_search_pages(client):
    cid = _corpus(client)
    kid = _kb(client, cid)
    client.post(f"/kbs/{kid}/pages", json={
        "type": "concept", "title": "Reranking", "description": "d",
        "body": "cross encoder scoring"})
    hits = client.get(f"/kbs/{kid}/search", params={"q": "cross encoder"}).json()
    assert [h["slug"] for h in hits] == ["reranking"]


def _kb_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mykb/kb.yaml", "name: Imported\ndescription: x\nformat: 1\ncreated: 2026-07-14\n")
        z.writestr("mykb/wiki/index.md", "# Index\n")
        z.writestr("mykb/wiki/log.md", "# Log\n")
        z.writestr("mykb/wiki/concepts/chunking.md",
                   "---\ntype: concept\ntitle: Chunking\ndescription: split\n"
                   "tags: []\ntimestamp: 2026-07-14\nsources: []\n---\n\nsplit text\n")
    return buf.getvalue()


def test_import_kb_creates_server_owned_kb(client):
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/kbs/import",
                    files={"archive": ("mykb.zip", _kb_zip(), "application/zip")},
                    data={"name": "Imported"})
    assert r.status_code == 201
    kid = r.json()["id"]
    pages = client.get(f"/kbs/{kid}").json()["pages"]
    assert [p["slug"] for p in pages] == ["chunking"]
    assert client.get(f"/kbs/{kid}/pages/chunking").json()["body"] == "split text"
