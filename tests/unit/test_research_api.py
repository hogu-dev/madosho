# tests/unit/test_research_api.py
"""Research control-plane endpoints. Enqueue seam overridden so
no Postgres/queue is needed; assert state transitions + payloads (sqlite DB)."""
from fastapi.testclient import TestClient

from madosho_server import api, db


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'rapi.db'}")
    db.create_all()
    enqueued = []
    api.app.dependency_overrides[api.get_enqueue_research] = lambda: (
        lambda session, run_id: enqueued.append(run_id))
    return TestClient(api.app), enqueued


def _corpus(client):
    return client.post("/corpora", json={"name": "rescorp"}).json()["id"]


def test_launch_creates_pending_and_enqueues(tmp_path):
    client, enqueued = _client(tmp_path)
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/research", json={
        "prompt": "How are sensor failures handled?",
        "source": "rag", "llm": {"provider": "openai", "model": "m"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["corpus_id"] == cid
    assert body["prompt"] == "How are sensor failures handled?"
    assert enqueued == [body["id"]]


def test_launch_rejects_missing_llm(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/research", json={"prompt": "q?"})
    assert r.status_code == 400
    assert "llm" in r.json()["detail"].lower()


def test_launch_rejects_bad_source(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    r = client.post(f"/corpora/{cid}/research", json={
        "prompt": "q?", "source": "telepathy", "llm": {"provider": "o", "model": "m"}})
    assert r.status_code == 422   # pydantic pattern rejection


def test_launch_404_unknown_corpus(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/corpora/9999/research", json={
        "prompt": "q?", "llm": {"provider": "o", "model": "m"}})
    assert r.status_code == 404


def test_list_and_get_with_report(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/research", json={
        "prompt": "q?", "llm": {"provider": "o", "model": "m"}}).json()["id"]
    # simulate the worker finishing: write a report directly
    with db.SessionLocal() as s:
        run = s.get(db.ResearchRun, rid)
        run.status = "done"
        run.report_markdown = "# Done"
        run.citations = [{"document_id": 1, "citation": "doc1"}]
        run.run_log = [{"round": 1, "kind": "llm"}]
        run.stop_reason = "final"
        s.commit()

    runs = client.get(f"/corpora/{cid}/research").json()
    assert [r["id"] for r in runs] == [rid]
    assert "report_markdown" not in runs[0]   # list view is light

    detail = client.get(f"/corpora/{cid}/research/{rid}").json()
    assert detail["report_markdown"] == "# Done"
    assert detail["citations"][0]["document_id"] == 1
    assert detail["run_log"][0]["kind"] == "llm"


def test_get_404_unknown_run(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    assert client.get(f"/corpora/{cid}/research/9999").status_code == 404


def test_cancel_sets_status(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/research", json={
        "prompt": "q?", "llm": {"provider": "o", "model": "m"}}).json()["id"]
    r = client.post(f"/research/{rid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    # verify via get
    detail = client.get(f"/corpora/{cid}/research/{rid}").json()
    assert detail["status"] == "cancelled"


def test_cancel_noop_on_terminal(tmp_path):
    client, _ = _client(tmp_path)
    cid = _corpus(client)
    rid = client.post(f"/corpora/{cid}/research", json={
        "prompt": "q?", "llm": {"provider": "o", "model": "m"}}).json()["id"]
    # mark run as done directly
    with db.SessionLocal() as s:
        run = s.get(db.ResearchRun, rid)
        run.status = "done"
        s.commit()
    r = client.post(f"/research/{rid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "done"   # unchanged, no error


def test_cancel_404_missing(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/research/9999/cancel")
    assert r.status_code == 404


def test_research_launch_reasoning_effort_override(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'rr.db'}"); db.create_all()
    client = TestClient(api.app)
    with db.SessionLocal() as s:
        c = db.Corpus(name="c"); s.add(c)
        s.add(db.LlmEndpoint(name="codex", provider="openai", model="m",
                             api_base="u", is_default=True, reasoning_effort="low"))
        s.commit(); cid = c.id
    r = client.post(f"/corpora/{cid}/research",
                    json={"prompt": "q", "llm": {"provider": "openai", "model": "m"},
                          "reasoning_effort": "medium"})
    assert r.status_code in (200, 201), r.text
    with db.SessionLocal() as s:
        run = s.query(db.ResearchRun).first()
        assert run.config["llm"]["reasoning_effort"] == "medium"
