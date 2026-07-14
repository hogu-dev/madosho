import os
import pytest
from fastapi.testclient import TestClient
from madosho_server import api, db


@pytest.fixture
def client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}"); db.create_all()
    return TestClient(api.app)


def test_crud_and_set_default(client, monkeypatch):
    monkeypatch.setenv("MADOSHO_LLM_API_KEY", "v")
    r = client.post("/llm-endpoints", json={"name": "gemma4-local", "provider": "openai",
        "model": "gemma-4-e4b", "api_base": "http://h:8081/v1",
        "key_env_var": "MADOSHO_LLM_API_KEY"})
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["is_default"] is True          # first row auto-defaults
    assert first["key_present"] is True
    assert "key" not in first and "api_key" not in first
    assert set(first.keys()) == {"id", "name", "provider", "model", "api_base",
                                 "key_env_var", "is_default", "key_present",
                                 "supports_text", "supports_vision", "is_vision_default",
                                 "api_flavor", "context_window_tokens",
                                 "source_chars_budget", "reasoning_effort"}
    assert first["api_flavor"] == "chat"        # default when unspecified

    r2 = client.post("/llm-endpoints", json={"name": "qwen", "provider": "openai",
        "model": "qwen3-14b", "api_base": "http://h:8081/v1", "key_env_var": None})
    second = r2.json()
    assert second["key_present"] is False

    client.put(f"/llm-endpoints/{second['id']}/default")
    rows = client.get("/llm-endpoints").json()
    by_id = {e["id"]: e for e in rows}
    assert by_id[second["id"]]["is_default"] is True
    assert by_id[first["id"]]["is_default"] is False

    assert client.delete(f"/llm-endpoints/{first['id']}").status_code == 204
    assert len(client.get("/llm-endpoints").json()) == 1


def test_delete_default_promotes_next(client, monkeypatch):
    monkeypatch.setenv("MADOSHO_LLM_API_KEY", "v")
    # POST endpoint "a" (first -> auto-default is_default True)
    r_a = client.post("/llm-endpoints", json={"name": "a", "provider": "openai",
        "model": "m-a", "api_base": "http://h:8081/v1",
        "key_env_var": "MADOSHO_LLM_API_KEY"})
    assert r_a.status_code == 201
    a = r_a.json()
    assert a["is_default"] is True

    # POST endpoint "b" (not default)
    r_b = client.post("/llm-endpoints", json={"name": "b", "provider": "openai",
        "model": "m-b", "api_base": "http://h:8081/v1",
        "key_env_var": "MADOSHO_LLM_API_KEY"})
    assert r_b.status_code == 201
    b = r_b.json()
    assert b["is_default"] is False

    # Confirm "a" is the default via GET list
    rows = client.get("/llm-endpoints").json()
    by_id = {e["id"]: e for e in rows}
    assert by_id[a["id"]]["is_default"] is True
    assert by_id[b["id"]]["is_default"] is False

    # DELETE "a" (the default)
    delete_r = client.delete(f"/llm-endpoints/{a['id']}")
    assert delete_r.status_code == 204

    # GET list -> only "b" remains AND b.is_default is now True (promoted)
    rows_after = client.get("/llm-endpoints").json()
    assert len(rows_after) == 1
    assert rows_after[0]["id"] == b["id"]
    assert rows_after[0]["is_default"] is True


def test_duplicate_name_409(client):
    body = {"name": "dup", "provider": "openai", "model": "m", "api_base": "u"}
    assert client.post("/llm-endpoints", json=body).status_code == 201
    assert client.post("/llm-endpoints", json=body).status_code == 409


def test_api_flavor_round_trip_and_update(client):
    r = client.post("/llm-endpoints", json={"name": "codex-proxy", "provider": "openai",
        "model": "gpt-5.5", "api_base": "http://proxy:10531/v1",
        "supports_vision": True, "api_flavor": "responses"})
    assert r.status_code == 201, r.text
    ep = r.json()
    assert ep["api_flavor"] == "responses"

    r2 = client.put(f"/llm-endpoints/{ep['id']}", json={"name": "codex-proxy",
        "provider": "openai", "model": "gpt-5.5", "api_base": "http://proxy:10531/v1",
        "supports_vision": True, "api_flavor": "chat"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["api_flavor"] == "chat"


def test_api_flavor_rejects_unknown_value(client):
    r = client.post("/llm-endpoints", json={"name": "bad", "provider": "openai",
        "model": "m", "api_base": "u", "api_flavor": "grpc"})
    assert r.status_code == 422


def test_create_rejects_no_capability(client):
    r = client.post("/llm-endpoints", json={
        "name": "nocap", "provider": "openai", "model": "m", "api_base": "u",
        "supports_text": False, "supports_vision": False})
    assert r.status_code == 422


def test_create_vision_endpoint_becomes_vision_default(client):
    r = client.post("/llm-endpoints", json={
        "name": "vis", "provider": "openai", "model": "gemma-4-e4b",
        "api_base": "http://h/v1", "supports_text": True, "supports_vision": True})
    assert r.status_code == 201
    body = r.json()
    assert body["supports_vision"] is True
    assert body["is_vision_default"] is True


def test_read_exposes_capabilities(client):
    client.post("/llm-endpoints", json={
        "name": "t", "provider": "openai", "model": "m", "api_base": "u"})
    rows = client.get("/llm-endpoints").json()
    assert rows[0]["supports_text"] is True
    assert rows[0]["supports_vision"] is False
    assert rows[0]["is_vision_default"] is False


def test_set_vision_default_route(client):
    a = client.post("/llm-endpoints", json={"name": "va", "provider": "o", "model": "m",
        "api_base": "u", "supports_text": True, "supports_vision": True}).json()
    b = client.post("/llm-endpoints", json={"name": "vb", "provider": "o", "model": "m",
        "api_base": "u", "supports_text": True, "supports_vision": True}).json()
    r = client.put(f"/llm-endpoints/{b['id']}/vision-default")
    assert r.status_code == 200 and r.json()["is_vision_default"] is True
    rows = {x["id"]: x for x in client.get("/llm-endpoints").json()}
    assert rows[a["id"]]["is_vision_default"] is False


def test_set_vision_default_rejects_non_vision(client):
    t = client.post("/llm-endpoints", json={"name": "t", "provider": "o", "model": "m",
        "api_base": "u", "supports_text": True, "supports_vision": False}).json()
    r = client.put(f"/llm-endpoints/{t['id']}/vision-default")
    assert r.status_code == 422


def test_set_vision_default_404(client):
    assert client.put("/llm-endpoints/9999/vision-default").status_code == 404


def test_set_default_route_rejects_non_text(client):
    v = client.post("/llm-endpoints", json={"name": "vo", "provider": "o", "model": "m",
        "api_base": "u", "supports_text": False, "supports_vision": True}).json()
    r = client.put(f"/llm-endpoints/{v['id']}/default")
    assert r.status_code == 422


def test_update_clears_default_when_text_removed(client):
    a = client.post("/llm-endpoints", json={"name": "a", "provider": "o", "model": "m",
        "api_base": "u", "supports_text": True, "supports_vision": True}).json()
    assert a["is_default"] is True
    upd = client.put(f"/llm-endpoints/{a['id']}", json={"name": "a", "provider": "o",
        "model": "m", "api_base": "u", "supports_text": False, "supports_vision": True}).json()
    assert upd["is_default"] is False


def test_context_metadata_round_trip(client):
    # Create with both fields set -> echoed back on read.
    r = client.post("/llm-endpoints", json={"name": "budgeted", "provider": "openai",
        "model": "granite-4", "api_base": "http://h/v1",
        "context_window_tokens": 8192, "source_chars_budget": 16000})
    assert r.status_code == 201, r.text
    ep = r.json()
    assert ep["context_window_tokens"] == 8192
    assert ep["source_chars_budget"] == 16000

    # Omitted on create -> null (the fields are optional).
    r2 = client.post("/llm-endpoints", json={"name": "plain", "provider": "openai",
        "model": "m", "api_base": "u"})
    assert r2.status_code == 201, r2.text
    plain = r2.json()
    assert plain["context_window_tokens"] is None
    assert plain["source_chars_budget"] is None

    # PUT rewrites the row from the body: a supplied field updates, an omitted
    # field resets to null (same full-replace semantics as the other columns).
    upd = client.put(f"/llm-endpoints/{ep['id']}", json={"name": "budgeted",
        "provider": "openai", "model": "granite-4", "api_base": "http://h/v1",
        "source_chars_budget": 20000})
    assert upd.status_code == 200, upd.text
    assert upd.json()["source_chars_budget"] == 20000
    assert upd.json()["context_window_tokens"] is None


def test_context_metadata_rejects_non_positive(client):
    # Field(ge=1): zero/negative are nonsensical budgets -> 422 before the DB.
    r = client.post("/llm-endpoints", json={"name": "bad", "provider": "o",
        "model": "m", "api_base": "u", "source_chars_budget": 0})
    assert r.status_code == 422
    r2 = client.post("/llm-endpoints", json={"name": "bad2", "provider": "o",
        "model": "m", "api_base": "u", "context_window_tokens": -1})
    assert r2.status_code == 422


def test_reasoning_effort_create_read_update_roundtrip(client):
    r = client.post("/llm-endpoints", json={"name": "codex", "provider": "openai",
        "model": "gpt-5.6-sol", "api_base": "http://h/v1", "reasoning_effort": "low"})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["reasoning_effort"] == "low"
    assert "reasoning_effort" in row.keys()

    upd = client.put(f"/llm-endpoints/{row['id']}", json={"name": "codex",
        "provider": "openai", "model": "gpt-5.6-sol", "api_base": "http://h/v1",
        "reasoning_effort": "high"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["reasoning_effort"] == "high"


def test_reasoning_effort_blank_becomes_unset(client):
    r = client.post("/llm-endpoints", json={"name": "e", "provider": "openai",
        "model": "m", "api_base": "http://h/v1", "reasoning_effort": "   "})
    assert r.status_code == 201, r.text
    assert r.json()["reasoning_effort"] is None   # whitespace-only -> unset


def test_reasoning_effort_omitted_is_none(client):
    r = client.post("/llm-endpoints", json={"name": "e2", "provider": "openai",
        "model": "m", "api_base": "http://h/v1"})
    assert r.status_code == 201, r.text
    assert r.json()["reasoning_effort"] is None


def test_reasoning_effort_over_cap_rejected(client):
    r = client.post("/llm-endpoints", json={"name": "e3", "provider": "openai",
        "model": "m", "api_base": "http://h/v1", "reasoning_effort": "x" * 33})
    assert r.status_code == 422


def test_list_endpoint_models_route(client, monkeypatch):
    from madosho_server import llm_endpoints
    r = client.post("/llm-endpoints", json={"name": "codex", "provider": "openai",
        "model": "gpt-5.5", "api_base": "http://proxy:10531/v1", "api_flavor": "responses"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"id": "gpt-5.6-sol"}, {"id": "codex-auto-review"}]}
    monkeypatch.setattr(llm_endpoints.httpx, "get", lambda *a, **k: _Resp())

    got = client.get(f"/llm-endpoints/{eid}/models")
    assert got.status_code == 200, got.text
    body = got.json()
    assert [m["id"] for m in body] == ["gpt-5.6-sol", "codex-auto-review"]
    assert body[0]["reasoning_efforts"][-1] == "max"
    assert body[1]["reasoning_efforts"] == []


def test_list_endpoint_models_404_for_unknown(client):
    assert client.get("/llm-endpoints/9999/models").status_code == 404
