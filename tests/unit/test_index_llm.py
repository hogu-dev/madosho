from types import SimpleNamespace

from madosho_server import db, tasks


def _mk_session(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'i.db'}"); db.create_all()


def test_index_llm_none_when_registry_empty(tmp_path):
    _mk_session(tmp_path)
    assert tasks._index_llm(tasks.Settings.from_env()) is None


def test_index_llm_uses_default_endpoint(tmp_path, monkeypatch):
    _mk_session(tmp_path)
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="g", provider="openai", model="gemma-4-e4b",
                             api_base="http://h:8081/v1", is_default=True)); s.commit()
    monkeypatch.setattr("madosho_server.llm_endpoints.complete",
        lambda **k: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]))
    call = tasks._index_llm(tasks.Settings.from_env())
    assert call("hi") == "ok"


def test_run_eval_defaults_provider_model_from_registry(tmp_path, monkeypatch):
    """run_eval must pick provider/model from the default registry endpoint when
    the EvalRun's sampling dict has no 'llm' key."""
    _mk_session(tmp_path)
    with db.SessionLocal() as s:
        c = db.Corpus(name="c", config={}); s.add(c); s.commit(); s.refresh(c)
        s.add(db.LlmEndpoint(name="ep", provider="openai", model="gpt-test",
                             api_base="http://h:1234/v1", is_default=True))
        run = db.EvalRun(corpus_id=c.id, status="pending", sampling={})
        s.add(run); s.commit(); s.refresh(run)
        run_id = run.id

    captured = {}

    def fake_eval_llm(settings, provider, model):
        captured["provider"] = provider
        captured["model"] = model
        return SimpleNamespace(tokens=0, provider=provider, model=model)

    monkeypatch.setattr(tasks, "_eval_llm", fake_eval_llm)
    monkeypatch.setattr(tasks, "execute_run",
                        lambda session, run_id, settings, llm, **kw: None)

    tasks.run_eval(run_id)

    assert captured.get("provider") == "openai"
    assert captured.get("model") == "gpt-test"


def test_run_eval_binds_endpoint_creds(tmp_path, monkeypatch):
    """run_eval must bind the default endpoint's own api_base and key_env_var
    onto the settings passed to _eval_llm (I1 fix: not just provider/model)."""
    _mk_session(tmp_path)
    monkeypatch.setenv("EVAL_KEY_VAR", "test-api-key-value")
    with db.SessionLocal() as s:
        c = db.Corpus(name="c2", config={}); s.add(c); s.commit(); s.refresh(c)
        s.add(db.LlmEndpoint(name="ep2", provider="openai", model="gpt-test",
                             api_base="http://eval-host:9/v1",
                             key_env_var="EVAL_KEY_VAR", is_default=True))
        run = db.EvalRun(corpus_id=c.id, status="pending", sampling={})
        s.add(run); s.commit(); s.refresh(run)
        run_id = run.id

    captured = {}

    def fake_eval_llm(settings, provider, model):
        captured["settings"] = settings
        captured["provider"] = provider
        captured["model"] = model
        return SimpleNamespace(tokens=0, provider=provider, model=model)

    monkeypatch.setattr(tasks, "_eval_llm", fake_eval_llm)
    monkeypatch.setattr(tasks, "execute_run",
                        lambda session, run_id, settings, llm, **kw: None)

    tasks.run_eval(run_id)

    assert captured["settings"].llm_api_base == "http://eval-host:9/v1"
    assert captured["settings"].llm_api_key == "test-api-key-value"
