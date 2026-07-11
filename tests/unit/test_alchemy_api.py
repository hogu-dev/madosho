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


def test_create_goal_include_generated_round_trips(tmp_path):
    """The include_generated create field lands on the DB row and comes back
    on both the create response and a subsequent read (work-unit exclusion,
    stage D). Server default is False (exclude); True is an explicit opt-in."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid)                 # default: not sent
    assert r.status_code == 201, r.text
    assert r.json()["include_generated"] is False

    r2 = _create_goal(client, cid, name="find_vuln_2", include_generated=True)
    assert r2.status_code == 201, r2.text
    assert r2.json()["include_generated"] is True
    got = client.get("/alchemy/goals/find_vuln_2")
    assert got.json()["include_generated"] is True


def test_create_goal_bad_corpus_404(tmp_path):
    client, _ = _client(tmp_path)
    r = _create_goal(client, 999)
    assert r.status_code == 404


def test_create_goal_bad_type_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="unknown-type")
    assert r.status_code == 400


REPORT_TEMPLATE = "# R\n\nintro\n\n## Summary\n\nshort.\n\n## Detail\n\nlong.\n"


def test_create_report_goal_201(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report",
                     spec={"template": REPORT_TEMPLATE})
    assert r.status_code == 201, r.text
    assert r.json()["goal_type"] == "report"


def test_create_report_goal_requires_template_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report", spec={"goal": "x"})
    assert r.status_code == 400
    assert "template" in r.json()["detail"]


def test_create_report_fields_goal_201(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report",
                     spec={"title": "R", "goal": "assess it",
                           "fields": [{"key": "summary",
                                       "instruction": "one line."}]})
    assert r.status_code == 201, r.text
    assert r.json()["goal_type"] == "report"


def test_create_report_fields_empty_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report", spec={"fields": []})
    assert r.status_code == 400


def test_create_report_goal_unparseable_template_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, goal_type="report",
                     spec={"template": "no headings, just prose"})
    assert r.status_code == 400
    assert "section" in r.json()["detail"]


def test_get_run_exposes_sections(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid, goal_type="report",
                 spec={"template": REPORT_TEMPLATE})
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}).json()["id"]
    with db.SessionLocal() as s:   # simulate the worker landing results
        run = s.get(db.AlchemyRun, rid)
        run.sections = [{"key": "summary", "title": "Summary",
                         "content": "ok", "filled": True, "note": "",
                         "confidence": {"level": "medium"},
                         "stop_reason": "final", "llm_calls": 2}]
        run.status = "done"
        s.commit()
    got = client.get("/alchemy/goals/find_vuln/runs/1").json()
    assert got["sections"][0]["key"] == "summary"
    # the list view stays light - no sections there
    listed = client.get("/alchemy/goals/find_vuln/runs").json()
    assert "sections" not in listed[0]


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
    # llm present but empty and NO default endpoint row seeded -> the route's
    # own 400 (with a default row this would fall back instead; see the
    # stage-E fallback tests below)
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
    """Stage C opens run-launch coverage to search|full|exhaustive; only a
    value outside that set is rejected, the same way AlchemyGoalCreate.coverage
    rejects it."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs",
                    json={"llm": {"provider": "openai", "model": "m"},
                          "coverage": "vibes"})
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


def test_run_default_based_on_skips_all_unfilled_report_run(tmp_path):
    """A report draft is always non-empty (placeholder skeleton), so a later
    zero-filled run must NOT shadow an earlier fully-filled one: the default
    based_on lands on the version with at least one filled section."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid, goal_type="report",
                 spec={"template": REPORT_TEMPLATE})
    r1 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    r2 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    with db.SessionLocal() as s:
        run1 = s.get(db.AlchemyRun, r1.json()["id"])
        run1.status = "done"
        run1.draft_markdown = "# R\n\n## Summary\n\nreal content\n"
        run1.sections = [{"key": "summary", "filled": True, "content": "x"},
                         {"key": "detail", "filled": False, "content": ""}]
        run2 = s.get(db.AlchemyRun, r2.json()["id"])
        run2.status = "done"
        run2.draft_markdown = "# R\n\n## Summary\n\n_(not filled: cancelled)_\n"
        run2.sections = [{"key": "summary", "filled": False, "content": ""},
                         {"key": "detail", "filled": False, "content": ""}]
        s.commit()
    r3 = client.post("/alchemy/goals/find_vuln/runs",
                     json={"llm": {"provider": "openai", "model": "m"}})
    assert r3.status_code == 201, r3.text
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


def _land_run(version):
    """Mark a run done-with-draft directly in the DB (the worker's job)."""
    with db.SessionLocal() as s:
        run = s.query(db.AlchemyRun).filter(
            db.AlchemyRun.version == version).first()
        run.status = "done"
        run.draft_markdown = "# Draft\nbody"
        s.commit()


def test_finalize_marks_version(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    _land_run(1)
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
    _land_run(1)
    _land_run(2)
    client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    client.post("/alchemy/goals/find_vuln/finalize", json={"version": 2})
    runs = {r["version"]: r["is_final"]
            for r in client.get("/alchemy/goals/find_vuln/runs").json()}
    assert runs[2] is True
    assert runs[1] is False


def test_finalize_pending_run_409(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    r = client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    assert r.status_code == 409


def test_finalize_done_but_empty_draft_409(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    with db.SessionLocal() as s:
        run = s.query(db.AlchemyRun).filter(
            db.AlchemyRun.version == 1).first()
        run.status = "done"
        run.draft_markdown = "   "
        s.commit()
    r = client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    assert r.status_code == 409


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


def test_run_detail_exposes_ledger(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}
                      ).json()["id"]
    with db.SessionLocal() as s:   # simulate the worker landing a ledger
        run = s.get(db.AlchemyRun, rid)
        run.ledger = {"mode": "search", "summary": "s"}
        run.status = "done"
        s.commit()
    got = client.get("/alchemy/goals/find_vuln/runs/1").json()
    assert got["ledger"] == {"mode": "search", "summary": "s"}
    # the list view stays light - no ledger there
    listed = client.get("/alchemy/goals/find_vuln/runs").json()
    assert "ledger" not in listed[0]


def test_goal_accepts_full_and_exhaustive_coverage(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    for cov in ("full", "exhaustive"):
        r = _create_goal(client, cid, name=f"covgoal-{cov}", coverage=cov)
        assert r.status_code == 201, r.text
        assert r.json()["coverage"] == cov


def test_goal_rejects_unknown_coverage(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = _create_goal(client, cid, name="badcov", coverage="vibes")
    assert r.status_code == 422


def test_run_launch_accepts_coverage_and_fresh_flag(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs", json={
        "llm": {"provider": "openai", "model": "m"}, "coverage": "full",
        "fresh_coverage": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["coverage"] == "full"
    # the flag rides in config for the worker
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, body["id"])
        assert run.config["fresh_coverage"] is True


def test_run_launch_rejects_unknown_coverage(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs", json={
        "llm": {"provider": "openai", "model": "m"}, "coverage": "vibes"})
    assert r.status_code == 422


def test_run_launch_concurrency_rides_config(tmp_path):
    """The per-run concurrency knob (stage E) lands in run.config for the
    worker; the run row itself needs no schema change."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs", json={
        "llm": {"provider": "openai", "model": "m"}, "concurrency": 4})
    assert r.status_code == 201, r.text
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, r.json()["id"])
        assert run.config["concurrency"] == 4


def test_run_launch_concurrency_defaults_to_1(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs",
                    json={"llm": {"provider": "openai", "model": "m"}})
    assert r.status_code == 201, r.text
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, r.json()["id"])
        assert run.config["concurrency"] == 1


def test_run_launch_concurrency_out_of_bounds_422(tmp_path):
    """Field(ge=1, le=8): 0 (meaningless) and 9 (beyond the parallelism cap)
    are rejected at the API edge, the same way max_llm_calls=0 is."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    for bad in (0, 9):
        r = client.post("/alchemy/goals/find_vuln/runs",
                        json={"llm": {"provider": "openai", "model": "m"},
                              "concurrency": bad})
        assert r.status_code == 422, f"concurrency={bad}: {r.text}"


def _seed_default_endpoint(provider="openai", model="gpt-default"):
    """A default LLM-endpoint registry row for the launch-fallback tests
    (stage E): the same is_default row resolve_llm picks for the query plane."""
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="default-ep", provider=provider, model=model,
                             api_base="http://llm", is_default=True))
        s.commit()


def test_run_launch_falls_back_to_default_endpoint(tmp_path):
    """No llm block at all -> the server resolves the default registry row and
    stamps the resolved provider/model into run.config, so the run record is
    explicit about what it actually used (no implicit-at-execute-time magic)."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _seed_default_endpoint()
    r = client.post("/alchemy/goals/find_vuln/runs", json={})
    assert r.status_code == 201, r.text
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, r.json()["id"])
        assert run.config["llm"] == {"provider": "openai",
                                     "model": "gpt-default"}


def test_run_launch_empty_llm_dict_falls_back_too(tmp_path):
    """{'llm': {}} (what a tool passing provider=None/model=None serializes
    to) behaves the same as omitting llm entirely."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _seed_default_endpoint()
    r = client.post("/alchemy/goals/find_vuln/runs", json={"llm": {}})
    assert r.status_code == 201, r.text
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, r.json()["id"])
        assert run.config["llm"]["model"] == "gpt-default"


def test_run_launch_no_llm_and_no_default_400(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.post("/alchemy/goals/find_vuln/runs", json={})
    assert r.status_code == 400
    assert "no default LLM endpoint" in r.json()["detail"]


def test_run_launch_partial_llm_400_even_with_default(tmp_path):
    """provider-without-model (or vice versa) is a user mistake, not a request
    for the default: silently swapping in a different provider/model pair
    would hide the typo, so it stays the plain 400."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _seed_default_endpoint()
    for partial in ({"provider": "openai"}, {"model": "m"}):
        r = client.post("/alchemy/goals/find_vuln/runs",
                        json={"llm": partial})
        assert r.status_code == 400, f"llm={partial}: {r.text}"


def test_run_launch_blank_llm_pair_400_even_with_default(tmp_path):
    """A present-but-BLANK pair ({'provider': '', 'model': ''}) is a client
    bug (e.g. a blanked-out form), not a request for the default: it must 400,
    not silently launch against the default endpoint. Only a fully-absent llm
    block ({} / omitted) means 'use the default'."""
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _seed_default_endpoint()
    for blank in ({"provider": "", "model": ""},
                  {"provider": "openai", "model": ""},
                  {"provider": "", "model": "m"}):
        r = client.post("/alchemy/goals/find_vuln/runs",
                        json={"llm": blank})
        assert r.status_code == 400, f"llm={blank}: {r.text}"


def test_run_launch_explicit_llm_ignores_default(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    _seed_default_endpoint(provider="other", model="fallback-m")
    r = client.post("/alchemy/goals/find_vuln/runs",
                    json={"llm": {"provider": "openai", "model": "m"}})
    assert r.status_code == 201, r.text
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, r.json()["id"])
        assert run.config["llm"] == {"provider": "openai", "model": "m"}


def _seed_artifacts(rid):
    """Simulate the worker landing artifacts on run `rid` (marks it done)."""
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, rid)
        run.status = "done"
        s.add(db.AlchemyArtifact(run_id=rid, goal_id=run.goal_id,
                                 kind="digest", key="doc-1",
                                 payload={"filename": "a.txt", "text": "x"}))
        s.add(db.AlchemyArtifact(run_id=rid, goal_id=run.goal_id,
                                 kind="handoff", key="body-h1",
                                 payload={"attempt": 1}))
        s.commit()


def test_list_run_artifacts(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}
                      ).json()["id"]
    _seed_artifacts(rid)
    rows = client.get("/alchemy/goals/find_vuln/runs/1/artifacts").json()
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"digest", "handoff"}
    digest = next(r for r in rows if r["kind"] == "digest")
    assert digest["key"] == "doc-1"
    assert digest["document_id"] is None
    assert digest["payload"]["filename"] == "a.txt"
    assert digest["created_at"]


def test_list_artifacts_bad_goal_404(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/alchemy/goals/nope/runs/1/artifacts")
    assert r.status_code == 404


def test_list_artifacts_bad_version_404(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    r = client.get("/alchemy/goals/find_vuln/runs/9/artifacts")
    assert r.status_code == 404


def test_run_detail_exposes_artifact_counts(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}
                      ).json()["id"]
    _seed_artifacts(rid)
    got = client.get("/alchemy/goals/find_vuln/runs/1").json()
    assert got["artifact_counts"] == {"digest": 1, "handoff": 1}


def test_delete_goal_removes_artifacts(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    _create_goal(client, cid)
    rid = client.post("/alchemy/goals/find_vuln/runs",
                      json={"llm": {"provider": "openai", "model": "m"}}
                      ).json()["id"]
    _seed_artifacts(rid)
    assert client.delete("/alchemy/goals/find_vuln").status_code == 200
    with db.SessionLocal() as s:
        assert s.query(db.AlchemyArtifact).count() == 0


def _ingest_ready(client, tmp_path, monkeypatch):
    """A goal with a done v1 (draft landed), plus the enqueue/filestore seams
    stubbed so the ingest path can create a real library row under sqlite."""
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    api.app.dependency_overrides[api.get_enqueue] = lambda: (lambda s, i: None)
    api.app.dependency_overrides[api.get_enqueue_build_pipeline] = lambda: (lambda s, i: None)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    _land_run(1)
    return cid


def test_ingest_route_creates_generated_document(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    r = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["origin"] == "generated"
    assert body["filename"] == "find_vuln-v1.md"
    assert body["origin_label"] == "[generated: find_vuln v1]"
    # the run records the produced document id, and an artifact row exists
    run = client.get("/alchemy/goals/find_vuln/runs/1").json()
    assert run["ingested_document_id"] == body["id"]
    with db.SessionLocal() as s:
        arts = s.query(db.AlchemyArtifact).filter(
            db.AlchemyArtifact.kind == "ingest").all()
        assert len(arts) == 1 and arts[0].document_id == body["id"]


def test_ingest_route_twice_is_idempotent(tmp_path, monkeypatch):
    # _ingest_bytes dedupes the DOCUMENT by content hash, so calling this
    # endpoint again for the same run returns the same document - the
    # bookkeeping artifact row must not double up alongside it.
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    first = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    second = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["id"] == second.json()["id"]   # same deduped document
    with db.SessionLocal() as s:
        arts = s.query(db.AlchemyArtifact).filter(
            db.AlchemyArtifact.kind == "ingest").all()
        assert len(arts) == 1
        assert arts[0].document_id == second.json()["id"]


def test_ingest_route_defaults_to_goal_corpus(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    r = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    did = r.json()["id"]
    chips = client.get(f"/documents/{did}").json()["corpora"]
    assert any(c["name"] == "secdocs" for c in chips)   # the goal's corpus


def test_ingest_route_pending_run_409(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    api.app.dependency_overrides[api.get_enqueue] = lambda: (lambda s, i: None)
    api.app.dependency_overrides[api.get_enqueue_build_pipeline] = lambda: (lambda s, i: None)
    cid = _corpus(client)
    _create_goal(client, cid)
    client.post("/alchemy/goals/find_vuln/runs",
                json={"llm": {"provider": "openai", "model": "m"}})
    # no _land_run -> still pending
    r = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    assert r.status_code == 409


def test_finalize_with_ingest_creates_generated_doc(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    r = client.post("/alchemy/goals/find_vuln/finalize",
                    json={"version": 1, "ingest": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_final"] is True
    assert body["ingested_document_id"] is not None


def test_finalize_without_ingest_does_not_create_doc(tmp_path, monkeypatch):
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    client.post("/alchemy/goals/find_vuln/finalize", json={"version": 1})
    run = client.get("/alchemy/goals/find_vuln/runs/1").json()
    assert run["ingested_document_id"] is None


def test_finalize_ingest_after_standalone_ingest_is_idempotent(tmp_path, monkeypatch):
    # A standalone /ingest followed by finalize --ingest on the same run walks
    # _ingest_run_draft twice; the resulting document is the same deduped row,
    # and the "this run produced doc N" bookkeeping must stay at one row.
    client, _ = _client(tmp_path)
    _ingest_ready(client, tmp_path, monkeypatch)
    standalone = client.post("/alchemy/goals/find_vuln/runs/1/ingest", json={})
    finalized = client.post("/alchemy/goals/find_vuln/finalize",
                            json={"version": 1, "ingest": True})
    assert standalone.status_code == 202 and finalized.status_code == 200
    assert finalized.json()["ingested_document_id"] == standalone.json()["id"]
    with db.SessionLocal() as s:
        arts = s.query(db.AlchemyArtifact).filter(
            db.AlchemyArtifact.kind == "ingest").all()
        assert len(arts) == 1
        assert arts[0].document_id == standalone.json()["id"]
