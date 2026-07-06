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


def test_duplicate_name_check_is_name_only(tmp_path):
    """A name that happens to be another goal's id string must not collide:
    the dup check must not fall back to id lookup like _resolve_goal does."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    first = _create_goal(client, cid)
    goal_id_str = str(first.json()["id"])
    r = _create_goal(client, cid, name=goal_id_str)
    assert r.status_code == 201, r.text


def test_create_goal_non_string_spec_goal_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, spec={"goal": 123})
    assert r.status_code == 400


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


def test_run_rejects_unsupported_coverage_422(tmp_path):
    """coverage="exhaustive" is not a stage-A value; the run launch body must
    reject it the same way AlchemyGoalCreate.coverage does."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs",
                    json={"llm": {"provider": "openai", "model": "m"},
                          "coverage": "exhaustive"})
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


def test_run_default_based_on_version_skips_draftless_later_run(tmp_path):
    """v1 gets a draft, v2 exists with no draft (e.g. a run that failed before
    producing one); the default for v3 must land on v1, not v2 or nothing."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r1 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    with db.SessionLocal() as s:
        run1 = s.get(db.AlchemyRun, r1.json()["id"])
        run1.draft_markdown = "# draft"
        run1.status = "done"
        s.commit()
    r3 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    assert r3.status_code == 201, r3.text
    assert r3.json()["version"] == 3
    assert r3.json()["based_on_version"] == 1


def test_list_alchemy_goals(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _create_goal(client, cid, name="other_goal")
    r = client.get("/alchemy/goals")
    assert r.status_code == 200
    names = {g["name"] for g in r.json()}
    assert {"find_vuln", "other_goal"} <= names


def test_list_alchemy_runs_ordered_version_desc(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    r = client.get("/alchemy/goals/find_vuln/runs")
    assert r.status_code == 200
    assert [run["version"] for run in r.json()] == [2, 1]


def test_finalize_marks_version(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    r = client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    assert r.status_code == 200
    assert r.json()["is_final"] is True


def test_finalize_is_exclusive_one_final_at_a_time(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    client.post("/alchemy/goals/find_vuln/finalize", json={"version": 2})
    runs = {r["version"]: r["is_final"]
            for r in client.get("/alchemy/goals/find_vuln/runs").json()}
    assert runs[2] is True
    assert runs[1] is False


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
