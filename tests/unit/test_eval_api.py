# tests/unit/test_eval_api.py
"""Eval control-plane endpoints. The eval-enqueue seam is overridden so
no real queue/Postgres is needed; we assert state transitions and payloads."""
from fastapi.testclient import TestClient

from madosho_server import api, db


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'api.db'}"); db.create_all()
    enqueued = []
    builds = []
    api.app.dependency_overrides[api.get_settings] = lambda: api.Settings(
        database_url=f"sqlite:///{tmp_path/'api.db'}", qdrant_url="http://q:6333",
        filestore_dir=str(tmp_path), corpora_dir=str(tmp_path))
    api.app.dependency_overrides[api.get_enqueue_eval] = lambda: (
        lambda session, run_id: enqueued.append(run_id))
    return TestClient(api.app), enqueued, builds


def _corpus(client):
    return client.post("/corpora", json={"name": "evalcorp"}).json()["id"]


def test_launch_eval_creates_run_and_enqueues(tmp_path):
    client, enqueued, _ = _client(tmp_path)
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/evals", json={
        "sampling": {"n_docs": 5, "questions_per_doc": 3,
                     "llm": {"provider": "openai", "model": "gemma-e4b"}},
        "token_budget": 50000})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["corpus_id"] == cid
    assert enqueued == [body["id"]]


def test_list_and_get_run(tmp_path):
    client, _, _ = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/evals", json={"sampling": {}}).json()["id"]
    runs = client.get(f"/corpora/{cid}/evals").json()
    assert [run["id"] for run in runs] == [rid]
    detail = client.get(f"/evals/{rid}").json()
    assert detail["id"] == rid and "progress" in detail


def test_cancel_sets_status(tmp_path):
    client, _, _ = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/evals", json={"sampling": {}}).json()["id"]
    assert client.post(f"/evals/{rid}/cancel").status_code == 200
    assert client.get(f"/evals/{rid}").json()["status"] == "cancelled"


def test_proposal_get_and_dismiss(tmp_path):
    client, enqueued, builds = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/evals", json={"sampling": {}}).json()["id"]
    # seed a proposal directly
    with db.SessionLocal() as s:
        p = db.ConfigProposal(corpus_id=cid, eval_run_id=rid,
                              proposed_config={"corpus": "evalcorp", "ingest": {}, "query": []},
                              evidence={"baseline": 0.4, "projected": 0.6, "lifts": []},
                              status="proposed")
        s.add(p); s.commit(); pid = p.id
    # The proposal is a read-only recommendation: it can be read and dismissed, not applied.
    got = client.get(f"/corpora/{cid}/proposal").json()
    assert got["id"] == pid and got["evidence"]["projected"] == 0.6
    r = client.post(f"/proposals/{pid}/dismiss")
    assert r.status_code == 200
    assert r.json() == {"status": "dismissed"}
    assert client.get(f"/corpora/{cid}/proposal").status_code == 404      # no longer "proposed"


def test_proposal_404_when_none(tmp_path):
    client, _, _ = _client(tmp_path)
    cid = _corpus(client)
    assert client.get(f"/corpora/{cid}/proposal").status_code == 404
