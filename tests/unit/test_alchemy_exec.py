import types

from madosho_server import alchemy_exec, db
from madosho_server.settings import Settings


def _seed(tmp_path, *, based_on=None, prior_draft=None, guidance=None):
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="secdocs"); s.add(c); s.flush()
        g = db.AlchemyGoal(name="find_vuln", corpus_id=c.id,
                           goal_type="living-research",
                           spec={"goal": "map vulns"}, coverage="search")
        s.add(g); s.flush()
        if based_on is not None:
            s.add(db.AlchemyRun(goal_id=g.id, version=based_on, status="done",
                                coverage="search", draft_markdown=prior_draft,
                                config={"llm": {"provider": "p", "model": "m"}}))
        run = db.AlchemyRun(goal_id=g.id, version=(based_on or 0) + 1,
                            status="pending", coverage="search",
                            guidance=guidance, based_on_version=based_on,
                            config={"llm": {"provider": "p", "model": "m"},
                                    "budget_chars": 5000, "max_rounds": 3})
        s.add(run); s.commit()
        return run.id


class FakeResult:
    def __init__(self):
        self.markdown = "# Draft\nbody"
        self.citations = [types.SimpleNamespace(document_id=1, pipeline_id=2,
                          pipeline="p", position=0, citation="doc 1 @0",
                          source="d.txt", score=0.9, quote="ev")]
        self.run_log = [{"round": 1, "kind": "llm"}]
        self.stop_reason = "final"
        self.usage = types.SimpleNamespace(llm_calls=2, prompt_tokens=30,
                     completion_tokens=20, total_tokens=50)


def test_execute_writes_draft_and_usage(tmp_path):
    rid = _seed(tmp_path)
    seen = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      guidance=None, prior_draft=None, should_cancel=None):
        seen.update(goal_type=goal_type, corpus=corpus, guidance=guidance,
                    prior_draft=prior_draft)
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        run = s.get(db.AlchemyRun, rid)
        assert run.status == "done"
        assert run.draft_markdown == "# Draft\nbody"
        assert run.stop_reason == "final"
        assert run.usage["total_tokens"] == 50
        assert run.usage["llm_calls"] == 2
        assert len(run.citations) == 1
        assert run.citations[0]["document_id"] == 1
    assert seen["corpus"] == "secdocs"


def test_execute_passes_prior_draft_on_rerun(tmp_path):
    rid = _seed(tmp_path, based_on=1, prior_draft="old body",
                guidance="dig into June")
    captured = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      guidance=None, prior_draft=None, should_cancel=None):
        captured.update(prior_draft=prior_draft, guidance=guidance)
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
    assert captured["prior_draft"] == "old body"
    assert captured["guidance"] == "dig into June"


def test_execute_real_path_wrapper_call_shape(tmp_path, monkeypatch):
    """Regression for the no-run_goal_fn (real) path: the runner wrapper
    forwards tools=None, llm=None, and should_cancel via **kw into
    _default_run_goal, so its signature must accept-and-ignore them, and the
    run config's budgets must thread through. Monkeypatches the module-global
    _default_run_goal so no research_agent/LLM/subprocess is touched."""
    rid = _seed(tmp_path)
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, rid)
        run.config = {"llm": {"provider": "p", "model": "m"},
                      "budget_chars": 5000, "max_rounds": 3,
                      "max_llm_calls": 7}
        s.commit()

    got = {}

    def stand_in(goal_type, spec, *, corpus, settings, guidance, prior_draft,
                 provider, model, budget_chars, max_rounds, max_llm_calls,
                 alchemy_run_id, tools=None, llm=None, should_cancel=None):
        got.update(tools=tools, llm=llm, should_cancel=should_cancel,
                   budget_chars=budget_chars, max_rounds=max_rounds,
                   max_llm_calls=max_llm_calls)
        return FakeResult()

    monkeypatch.setattr(alchemy_exec, "_default_run_goal", stand_in)
    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env())
        assert s.get(db.AlchemyRun, rid).status == "done"
    assert got["tools"] is None
    assert got["llm"] is None
    assert callable(got["should_cancel"])
    assert got["budget_chars"] == 5000
    assert got["max_rounds"] == 3
    assert got["max_llm_calls"] == 7


def test_execute_missing_llm_fails(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c"); s.add(c); s.flush()
        g = db.AlchemyGoal(name="g", corpus_id=c.id,
                           goal_type="living-research", spec={"goal": "x"},
                           coverage="search"); s.add(g); s.flush()
        run = db.AlchemyRun(goal_id=g.id, version=1, status="pending",
                            coverage="search", config={"llm": {}})
        s.add(run); s.commit()
        alchemy_exec.execute_alchemy_run(s, run.id, Settings.from_env(),
                                         run_goal_fn=lambda *a, **k: None)
        assert s.get(db.AlchemyRun, run.id).status == "failed"
