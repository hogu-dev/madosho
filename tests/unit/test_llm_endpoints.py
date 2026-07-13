import pytest
from madosho_server import db


@pytest.fixture
def session(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'e.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        yield s


def test_create_endpoint_and_unique_name(session):
    session.add(db.LlmEndpoint(name="gemma4-local", provider="openai",
                               model="gemma-4-e4b", api_base="http://h:8081/v1",
                               key_env_var="MADOSHO_LLM_API_KEY", is_default=True))
    session.commit()
    row = session.query(db.LlmEndpoint).one()
    assert row.name == "gemma4-local"
    assert row.is_default is True
    assert row.key_env_var == "MADOSHO_LLM_API_KEY"


def test_set_default_flips_others_off(session):
    a = db.LlmEndpoint(name="a", provider="openai", model="m", api_base="u", is_default=True)
    b = db.LlmEndpoint(name="b", provider="openai", model="m", api_base="u", is_default=False)
    session.add_all([a, b]); session.commit()
    db.set_default_endpoint(session, b.id)
    session.refresh(a); session.refresh(b)
    assert a.is_default is False
    assert b.is_default is True


def test_set_default_raises_on_missing_id(session):
    with pytest.raises(ValueError):
        db.set_default_endpoint(session, 9999)


from dataclasses import replace
from madosho_server.settings import Settings

BASE = Settings(database_url="sqlite://", qdrant_url="", filestore_dir="",
                corpora_dir="")


def test_seed_inserts_default_when_empty_and_env_set(session):
    s = replace(BASE, index_llm_provider="openai", index_llm_model="gemma-4-e4b",
                llm_api_base="http://h:8081/v1")
    assert db.seed_llm_endpoints_from_env(s) is True
    row = session.query(db.LlmEndpoint).one()
    assert row.is_default is True
    assert (row.provider, row.model, row.api_base) == ("openai", "gemma-4-e4b", "http://h:8081/v1")


def test_seed_is_noop_when_rows_exist(session):
    session.add(db.LlmEndpoint(name="x", provider="openai", model="m",
                               api_base="u", is_default=True)); session.commit()
    s = replace(BASE, index_llm_provider="openai", index_llm_model="m")
    assert db.seed_llm_endpoints_from_env(s) is False
    assert session.query(db.LlmEndpoint).count() == 1


def test_seed_is_noop_when_env_unset(session):
    assert db.seed_llm_endpoints_from_env(BASE) is False
    assert session.query(db.LlmEndpoint).count() == 0


from types import SimpleNamespace
from madosho_server import llm_endpoints


def test_resolve_returns_none_when_empty(session):
    call, row = llm_endpoints.resolve_llm(session, BASE)
    assert call is None and row is None


def test_resolve_binds_endpoint_creds(session, monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret-xyz")
    session.add(db.LlmEndpoint(name="g", provider="openai", model="gemma-4-e4b",
                               api_base="http://h:8081/v1", key_env_var="MY_KEY",
                               is_default=True)); session.commit()

    captured = {}
    def fake_complete(messages, provider, model, settings, stream=False,
                      reasoning_effort=None):
        captured.update(provider=provider, model=model,
                        api_base=settings.llm_api_base, api_key=settings.llm_api_key)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ctx"))])
    monkeypatch.setattr(llm_endpoints, "complete", fake_complete)

    call, row = llm_endpoints.resolve_llm(session, BASE)
    assert call("hi") == "ctx"
    assert captured == {"provider": "openai", "model": "gemma-4-e4b",
                        "api_base": "http://h:8081/v1", "api_key": "secret-xyz"}
    assert row.name == "g"


def test_new_endpoint_defaults_text_only(session):
    e = db.LlmEndpoint(name="cap", provider="openai", model="m", api_base="u")
    session.add(e); session.commit(); session.refresh(e)
    assert e.supports_text is True
    assert e.supports_vision is False
    assert e.is_vision_default is False
    assert e.api_flavor == "chat"


def test_resolve_llm_responses_flavor_uses_respond(session, monkeypatch):
    monkeypatch.setenv("RK", "rsecret")
    session.add(db.LlmEndpoint(name="proxy", provider="openai", model="gpt-5.5",
                               api_base="http://proxy:10531/v1", key_env_var="RK",
                               is_default=True, api_flavor="responses"))
    session.commit()

    captured = {}
    def fake_respond(input_data, provider, model, settings, reasoning_effort=None):
        captured.update(input_data=input_data, provider=provider, model=model,
                        api_base=settings.llm_api_base, api_key=settings.llm_api_key)
        return "R-TEXT"
    monkeypatch.setattr(llm_endpoints, "respond", fake_respond)
    # complete() must NOT be touched on the responses path
    monkeypatch.setattr(llm_endpoints, "complete",
                        lambda *a, **k: pytest.fail("chat path used for responses flavor"))

    call, row = llm_endpoints.resolve_llm(session, BASE)
    assert call("hello") == "R-TEXT"
    assert captured == {"input_data": "hello", "provider": "openai",
                        "model": "gpt-5.5", "api_base": "http://proxy:10531/v1",
                        "api_key": "rsecret"}
    assert row.api_flavor == "responses"


def test_seed_marks_endpoint_text_and_vision_default(session):
    s = replace(BASE, index_llm_provider="openai", index_llm_model="gemma-4-e4b",
                llm_api_base="http://h:8081/v1")
    assert db.seed_llm_endpoints_from_env(s) is True
    row = session.query(db.LlmEndpoint).one()
    assert row.is_default is True
    assert row.supports_text is True
    assert row.supports_vision is True
    assert row.is_vision_default is True


def test_set_vision_default_flips_others_off(session):
    a = db.LlmEndpoint(name="va", provider="o", model="m", api_base="u",
                       supports_vision=True, is_vision_default=True)
    b = db.LlmEndpoint(name="vb", provider="o", model="m", api_base="u",
                       supports_vision=True, is_vision_default=False)
    session.add_all([a, b]); session.commit()
    db.set_vision_default_endpoint(session, b.id)
    session.refresh(a); session.refresh(b)
    assert a.is_vision_default is False
    assert b.is_vision_default is True


def test_set_vision_default_rejects_non_vision(session):
    t = db.LlmEndpoint(name="t", provider="o", model="m", api_base="u",
                       supports_text=True, supports_vision=False)
    session.add(t); session.commit()
    with pytest.raises(ValueError):
        db.set_vision_default_endpoint(session, t.id)


def test_set_vision_default_raises_on_missing_id(session):
    with pytest.raises(ValueError):
        db.set_vision_default_endpoint(session, 9999)


def test_set_default_rejects_non_text(session):
    v = db.LlmEndpoint(name="vis", provider="o", model="m", api_base="u",
                       supports_text=False, supports_vision=True)
    session.add(v); session.commit()
    with pytest.raises(ValueError):
        db.set_default_endpoint(session, v.id)


def test_resolve_vision_returns_none_when_no_vision_default(session):
    session.add(db.LlmEndpoint(name="t", provider="openai", model="m", api_base="u",
                               is_default=True, supports_text=True, supports_vision=False))
    session.commit()
    assert llm_endpoints.resolve_vision_endpoint(session, BASE) is None


def test_resolve_vision_binds_creds(session, monkeypatch):
    monkeypatch.setenv("VK", "vsecret")
    session.add(db.LlmEndpoint(name="v", provider="openai", model="gemma-4-e4b",
                               api_base="http://h:8081/v1", key_env_var="VK",
                               supports_text=True, supports_vision=True,
                               is_vision_default=True)); session.commit()
    resolved = llm_endpoints.resolve_vision_endpoint(session, BASE)
    assert resolved is not None
    provider, model, bound, flavor = resolved
    assert provider == "openai" and model == "gemma-4-e4b"
    assert bound.llm_api_base == "http://h:8081/v1"
    assert bound.llm_api_key == "vsecret"
    assert flavor == "chat"


def test_seed_name_matches_endpoint_name_pattern():
    from pydantic import ValidationError
    from madosho_server.api import LlmEndpointCreate

    # the name the env-seed assigns must be editable via PUT (same validator)
    # construct with the seed name: should succeed
    valid_endpoint = LlmEndpointCreate(
        name="default from env",
        provider="openai",
        model="m",
        api_base="http://localhost:8000",
        supports_text=True,
        supports_vision=True
    )
    assert valid_endpoint.name == "default from env"

    # construct with the old name (with parens): should raise ValidationError
    with pytest.raises(ValidationError):
        LlmEndpointCreate(
            name="default (from env)",
            provider="openai",
            model="m",
            api_base="http://localhost:8000",
            supports_text=True,
            supports_vision=True
        )


def test_endpoint_budget_resolves_metadata(session):
    session.add(db.LlmEndpoint(name="granite", provider="openai",
                               model="granite-4", api_base="u",
                               source_chars_budget=16000,
                               context_window_tokens=8192))
    session.commit()
    # (source_chars_budget, context_window_tokens) - budget first, matching the
    # order alchemy_exec unpacks (it only needs the source budget).
    assert llm_endpoints.endpoint_budget(session, "openai", "granite-4") == (16000, 8192)


def test_endpoint_budget_none_when_row_has_no_metadata(session):
    session.add(db.LlmEndpoint(name="plain", provider="openai", model="m",
                               api_base="u"))
    session.commit()
    assert llm_endpoints.endpoint_budget(session, "openai", "m") == (None, None)


def test_endpoint_budget_unknown_provider_model_returns_none(session):
    session.add(db.LlmEndpoint(name="plain", provider="openai", model="m",
                               api_base="u", source_chars_budget=9000))
    session.commit()
    # no row matches -> (None, None), never a partial/other-row value.
    assert llm_endpoints.endpoint_budget(session, "nope", "nope") == (None, None)


def test_endpoint_budget_prefers_default_row_when_multiple_match(session):
    # Two rows share (provider, model); the default one wins so the budget
    # tracks the endpoint a run would actually resolve to.
    session.add_all([
        db.LlmEndpoint(name="a", provider="openai", model="m", api_base="u",
                       source_chars_budget=1000, is_default=False),
        db.LlmEndpoint(name="b", provider="openai", model="m", api_base="u",
                       source_chars_budget=2000, is_default=True),
    ])
    session.commit()
    assert llm_endpoints.endpoint_budget(session, "openai", "m") == (2000, None)


def test_reasoning_effort_column_roundtrips(tmp_path):
    from madosho_server import db
    db.configure_engine(f"sqlite:///{tmp_path/'re.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="codex", provider="openai", model="gpt-5.6-sol",
                             api_base="http://h/v1", reasoning_effort="low"))
        s.add(db.LlmEndpoint(name="legacy", provider="openai", model="m",
                             api_base="http://h/v1"))
        s.commit()
    with db.SessionLocal() as s:
        rows = {r.name: r for r in s.query(db.LlmEndpoint).all()}
        assert rows["codex"].reasoning_effort == "low"
        assert rows["legacy"].reasoning_effort is None   # nullable, defaults to unset


def test_resolve_llm_binds_endpoint_reasoning_effort(tmp_path, monkeypatch):
    from madosho_server import db, llm, llm_endpoints
    from madosho_server.settings import Settings
    db.configure_engine(f"sqlite:///{tmp_path/'re2.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="codex", provider="openai", model="m",
                             api_base="http://h/v1", is_default=True,
                             reasoning_effort="low"))
        s.commit()
        settings = Settings(database_url="sqlite://", qdrant_url="",
                            filestore_dir="", corpora_dir="")
        captured = {}
        monkeypatch.setattr(
            llm, "completion",
            lambda **kw: (captured.update(kw),
                          __import__("types").SimpleNamespace(
                              choices=[__import__("types").SimpleNamespace(
                                  message=__import__("types").SimpleNamespace(
                                      content="ok"))]))[1])
        call, row = llm_endpoints.resolve_llm(s, settings)
        call("hello")
        assert captured["reasoning_effort"] == "low"
