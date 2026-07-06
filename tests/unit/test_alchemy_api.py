# tests/unit/test_alchemy_api.py
"""Alchemy control-plane endpoints. The alchemy-enqueue seam is overridden so
no real queue/Postgres is needed; we assert state transitions and payloads."""
from fastapi.testclient import TestClient

from madosho_server import api, db


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'aapi.db'}")
    db.create_all()
    enqueued = []
    api.app.dependency_overrides[api.get_enqueue_alchemy] = lambda: (
        lambda session, run_id: enqueued.append(run_id))
    return TestClient(api.app), enqueued


def _corpus(client):
    return client.post("/corpora", json={"name": "secdocs"}).json()["id"]


def _create_goal(client, corpus_id, **over):
    body = {"name": "find_vuln", "corpus_id": corpus_id,
            "goal_type": "living-research", "spec": {"goal": "map vulns"},
            "coverage": "search"}
    body.update(over)
    return client.post("/alchemy/goals", json=body)


def test_create_goal(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "find_vuln"


def test_create_goal_bad_corpus_404(tmp_path):
    client, _ = _client(tmp_path)
    r = _create_goal(client, 999)
    assert r.status_code == 404


def test_create_goal_bad_type_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report")   # stage B
    assert r.status_code == 400


def test_duplicate_name_409(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = _create_goal(client, cid)
    assert r.status_code == 409


def test_run_assigns_incrementing_versions(tmp_path):
    client, enqueued = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r1 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    r2 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    assert r1.json()["version"] == 1
    assert r2.json()["version"] == 2
    assert enqueued == [r1.json()["id"], r2.json()["id"]]


def test_run_requires_llm_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    # llm present but empty -> the route's own 400 (a missing llm key entirely
    # is Pydantic's 422, which needs no test of ours)
    r = client.post("/alchemy/goals/find_vuln/runs", json={"llm": {}})
    assert r.status_code == 400


def test_run_rejects_zero_max_llm_calls_422(tmp_path):
    """max_llm_calls=0 is meaningless (the engine would raise on its first
    forced-synthesis call); the API edge rejects it via Field(ge=1)."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs",
                    json={"llm": {"provider": "openai", "model": "m"},
                          "max_llm_calls": 0})
    assert r.status_code == 422


def test_get_goal_by_id_and_name(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    assert client.get("/alchemy/goals/find_vuln").status_code == 200
    assert client.get("/alchemy/goals/1").status_code == 200


def test_get_run_with_draft(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}).json()["id"]
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, rid)
        run.draft_markdown = "# draft"
        run.status = "done"
        s.commit()
    r = client.get("/alchemy/goals/find_vuln/runs/1")
    assert r.json()["draft_markdown"] == "# draft"


def test_finalize_marks_version(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    r = client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    assert r.status_code == 200
    assert r.json()["is_final"] is True


def test_cancel_run(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}).json()["id"]
    r = client.post(f"/alchemy/runs/{rid}/cancel")
    assert r.json()["status"] == "cancelled"


def test_delete_goal_removes_runs(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    assert client.delete("/alchemy/goals/find_vuln").status_code == 200
    assert client.get("/alchemy/goals/find_vuln").status_code == 404
