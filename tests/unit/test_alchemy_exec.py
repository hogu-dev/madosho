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
        self.sections = [{"key": "summary", "title": "Summary",
                          "content": "ok", "filled": True, "note": "",
                          "confidence": {"level": "medium"},
                          "stop_reason": "final", "llm_calls": 2}]
        self.ledger = {}


def test_execute_writes_draft_and_usage(tmp_path):
    rid = _seed(tmp_path)
    seen = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
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
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
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
                 alchemy_run_id, tools=None, llm=None, should_cancel=None,
                 coverage="search", prior_sections=None, prior_ledger=None,
                 on_progress=None):
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


def test_execute_honours_cancel_set_during_run(tmp_path):
    """If a cancel is written during the run (simulating an external API call),
    the worker should finish with status 'cancelled', not 'done'."""
    rid = _seed(tmp_path)

    def cancelling_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                            coverage="search", guidance=None, prior_draft=None,
                            prior_sections=None, prior_ledger=None,
                            on_progress=None, should_cancel=None):
        # simulate an external cancel arriving while the goal is working, via
        # a separate session/connection (as a real API request would use)
        with db.SessionLocal() as s2:
            row = s2.get(db.AlchemyRun, rid)
            row.status = "cancelled"
            s2.commit()
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=cancelling_run_goal)

    with db.SessionLocal() as s:
        got = s.get(db.AlchemyRun, rid)
        assert got.status == "cancelled"
        assert got.finished_at is not None
        # The goal finished its work before the cancel was observed, so the
        # draft it produced must be persisted - the flush() before the
        # cancel-check (and the expire_all() inside it) must not discard it.
        assert got.draft_markdown is not None
        assert got.draft_markdown == "# Draft\nbody"


def test_make_cancel_check_polarity(tmp_path):
    rid = _seed(tmp_path)
    should_cancel = alchemy_exec._make_cancel_check(rid)
    assert should_cancel() is False   # still "pending" (not started running)
    with db.SessionLocal() as s2:
        row = s2.get(db.AlchemyRun, rid)
        row.status = "cancelled"
        s2.commit()
    assert should_cancel() is True


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


def test_execute_persists_sections(tmp_path):
    rid = _seed(tmp_path)

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        run = s.get(db.AlchemyRun, rid)
        assert run.sections[0]["key"] == "summary"
        assert run.sections[0]["confidence"]["level"] == "medium"


def test_execute_passes_prior_sections_on_rerun(tmp_path):
    rid = _seed(tmp_path, based_on=1, prior_draft="old body")
    with db.SessionLocal() as s:   # give the v1 run stored sections
        prior = s.query(db.AlchemyRun).filter(
            db.AlchemyRun.version == 1).first()
        prior.sections = [{"key": "summary", "content": "old summary"}]
        s.commit()
    captured = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        captured.update(prior_sections=prior_sections)
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
    assert captured["prior_sections"] == [{"key": "summary",
                                           "content": "old summary"}]


def test_execute_progress_callback_writes_row(tmp_path):
    rid = _seed(tmp_path)

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        on_progress({"phase": "running", "section": "summary",
                     "sections_done": 0, "sections_total": 2})
        with db.SessionLocal() as s2:
            assert s2.get(db.AlchemyRun, rid).progress["section"] == "summary"
        return FakeResult()

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        assert s.get(db.AlchemyRun, rid).status == "done"


def test_execute_maps_failed_stop_reason_to_failed_status(tmp_path):
    """A report run whose engine caught a unit crash returns stop_reason
    'failed' with partial sections landed; the adapter must persist those
    sections, mark the run failed, and surface the failing section's note."""
    rid = _seed(tmp_path)

    class FailedResult(FakeResult):
        def __init__(self):
            super().__init__()
            self.stop_reason = "failed"
            self.sections = [
                {"key": "a", "title": "A", "content": "landed", "filled": True,
                 "note": "", "confidence": {"level": "medium"},
                 "stop_reason": "final", "llm_calls": 2},
                {"key": "b", "title": "B", "content": "", "filled": False,
                 "note": "unit failed: RuntimeError: boom",
                 "confidence": {"level": "low"}, "stop_reason": "", "llm_calls": 0}]

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(
            s, rid, Settings.from_env(),
            run_goal_fn=lambda *a, **kw: FailedResult())
        run = s.get(db.AlchemyRun, rid)
        assert run.status == "failed"
        assert run.error == "unit failed: RuntimeError: boom"
        # the partial result is kept, not discarded
        assert run.draft_markdown == "# Draft\nbody"
        assert [sec["key"] for sec in run.sections] == ["a", "b"]
        assert run.sections[0]["filled"] is True


def test_execute_maps_failed_with_carried_prior_note_to_error(tmp_path):
    """A rerun crash whose failing section carried prior content rewrites the
    note as 'unit failed (carried prior, not revised): <detail>' (orchestrator
    _carry_prior); the adapter's note match must still find it (no colon after
    'unit failed') so run.error is not silently lost to None."""
    rid = _seed(tmp_path)

    class FailedCarriedResult(FakeResult):
        def __init__(self):
            super().__init__()
            self.stop_reason = "failed"
            self.sections = [
                {"key": "a", "title": "A", "content": "landed", "filled": True,
                 "note": "", "confidence": {"level": "medium"},
                 "stop_reason": "final", "llm_calls": 2},
                {"key": "b", "title": "B", "content": "prior text",
                 "filled": True,
                 "note": "unit failed (carried prior, not revised): "
                         "RuntimeError: boom",
                 "confidence": {"level": "low"}, "stop_reason": "failed",
                 "llm_calls": 0}]

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(
            s, rid, Settings.from_env(),
            run_goal_fn=lambda *a, **kw: FailedCarriedResult())
        run = s.get(db.AlchemyRun, rid)
        assert run.status == "failed"
        assert run.error is not None
        assert "RuntimeError: boom" in run.error


def test_dataclass_sections_serialized(tmp_path):
    rid = _seed(tmp_path)
    from alchemy.types import SectionResult

    class DcResult(FakeResult):
        def __init__(self):
            super().__init__()
            self.sections = [SectionResult(key="a", title="A", content="x",
                                           filled=True,
                                           confidence={"level": "low"})]

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(
            s, rid, Settings.from_env(),
            run_goal_fn=lambda *a, **kw: DcResult())
        got = s.get(db.AlchemyRun, rid).sections
        assert got == [{"key": "a", "title": "A", "content": "x",
                        "filled": True, "note": "",
                        "confidence": {"level": "low"},
                        "stop_reason": "", "llm_calls": 0}]


def _seed_v2(tmp_path, *, v1_ledger=None, fresh=False):
    """Seed a goal with a done v1 (carrying a ledger) and a pending v2 that
    revises it. Returns (db_path-configured, v2_run_id)."""
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="secdocs"); s.add(c); s.flush()
        g = db.AlchemyGoal(name="find_vuln", corpus_id=c.id,
                           goal_type="living-research",
                           spec={"goal": "map vulns"}, coverage="search")
        s.add(g); s.flush()
        s.add(db.AlchemyRun(goal_id=g.id, version=1, status="done",
                            coverage="search", draft_markdown="v1 draft",
                            ledger=v1_ledger or {},
                            config={"llm": {"provider": "p", "model": "m"}}))
        cfg = {"llm": {"provider": "p", "model": "m"}}
        if fresh:
            cfg["fresh_coverage"] = True
        v2 = db.AlchemyRun(goal_id=g.id, version=2, status="pending",
                           coverage="search", based_on_version=1, config=cfg)
        s.add(v2); s.commit()
        return v2.id


def test_exec_persists_ledger_and_passes_coverage(tmp_path):
    rid = _seed(tmp_path)
    seen = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        seen.update(coverage=coverage, prior_ledger=prior_ledger)
        r = FakeResult()
        r.ledger = {"mode": "search", "summary": "ok"}
        return r

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        assert s.get(db.AlchemyRun, rid).ledger == {"mode": "search",
                                                    "summary": "ok"}
    assert seen["coverage"] == "search"
    assert seen["prior_ledger"] is None


def test_exec_passes_prior_ledger_from_based_on_run(tmp_path):
    rid = _seed_v2(tmp_path, v1_ledger={"consulted": {"3": "search"}})
    seen = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        seen["prior_ledger"] = prior_ledger
        r = FakeResult(); r.ledger = {}
        return r

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
    assert seen["prior_ledger"] == {"consulted": {"3": "search"}}


def test_exec_fresh_coverage_skips_prior_ledger(tmp_path):
    rid = _seed_v2(tmp_path, v1_ledger={"consulted": {"3": "search"}},
                   fresh=True)
    seen = {}

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        seen["prior_ledger"] = prior_ledger
        r = FakeResult(); r.ledger = {}
        return r

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
    assert seen["prior_ledger"] is None


def _stand_in_capturing(got):
    """A fixed-signature stand-in for _default_run_goal (the file's real-path
    style, matching test_execute_real_path_wrapper_call_shape) that records the
    derived budget_chars and returns a canned result."""
    def stand_in(goal_type, spec, *, corpus, settings, guidance, prior_draft,
                 provider, model, budget_chars, max_rounds, max_llm_calls,
                 alchemy_run_id, tools=None, llm=None, should_cancel=None,
                 coverage="search", prior_sections=None, prior_ledger=None,
                 on_progress=None):
        got["budget_chars"] = budget_chars
        return FakeResult()
    return stand_in


def test_exec_uses_registry_source_budget(tmp_path, monkeypatch):
    # A registry row for this run's (provider, model) carries a source budget:
    # it overrides the run config's budget_chars (5000) because a per-model
    # budget is the tuned value for the model actually assigned.
    rid = _seed(tmp_path)
    with db.SessionLocal() as s:
        s.add(db.LlmEndpoint(name="p-m", provider="p", model="m", api_base="u",
                             source_chars_budget=16000))
        s.commit()
    got = {}
    monkeypatch.setattr(alchemy_exec, "_default_run_goal", _stand_in_capturing(got))
    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env())
        assert s.get(db.AlchemyRun, rid).status == "done"
    assert got["budget_chars"] == 16000


def test_exec_falls_back_to_config_budget_when_no_registry_metadata(tmp_path, monkeypatch):
    # No matching row (or a row without a budget) -> endpoint_budget returns
    # (None, None) and the run config's budget_chars (5000) is used.
    rid = _seed(tmp_path)
    got = {}
    monkeypatch.setattr(alchemy_exec, "_default_run_goal", _stand_in_capturing(got))
    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env())
        assert s.get(db.AlchemyRun, rid).status == "done"
    assert got["budget_chars"] == 5000


def test_progress_writer_suppressed_on_terminal_row(tmp_path):
    """A late progress event from a cancelled run must not clobber the
    terminal row (the status-guard suppression path in
    _make_progress_writer)."""
    from madosho_server.alchemy_exec import _make_progress_writer
    rid = _seed(tmp_path)
    with db.SessionLocal() as s:
        run = s.get(db.AlchemyRun, rid)
        run.status = "cancelled"
        run.progress = {"phase": "done"}
        s.commit()
    writer = _make_progress_writer(rid)   # opens its own SessionLocal
    writer({"phase": "running", "section": "late"})
    with db.SessionLocal() as s:
        assert s.get(db.AlchemyRun, rid).progress == {"phase": "done"}


def test_execute_persists_artifacts(tmp_path):
    rid = _seed(tmp_path)

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        r = FakeResult()
        # the engine emits plain dicts (DB-free); the adapter turns them into rows
        r.artifacts = [
            {"kind": "digest", "key": "doc-1",
             "payload": {"document_id": 1, "filename": "a.txt",
                         "text": "digest one"}},
            {"kind": "handoff", "key": "body-h1",
             "payload": {"unit": "body", "attempt": 1, "trigger": "round_cap",
                         "docs_covered": [1], "remaining": "more",
                         "partial_chars": 42}},
        ]
        return r

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        run = s.get(db.AlchemyRun, rid)
        arts = s.query(db.AlchemyArtifact).filter(
            db.AlchemyArtifact.run_id == rid).order_by(
            db.AlchemyArtifact.id).all()
        assert len(arts) == 2
        assert {a.kind for a in arts} == {"digest", "handoff"}
        # run_id + goal_id are derived from the run/goal rows, not the payload
        assert all(a.goal_id == run.goal_id for a in arts)
        assert all(a.document_id is None for a in arts)   # not indexed yet
        digest = next(a for a in arts if a.kind == "digest")
        assert digest.payload["filename"] == "a.txt"


def test_execute_no_artifacts_when_result_has_none(tmp_path):
    rid = _seed(tmp_path)

    def fake_run_goal(goal_type, spec, *, corpus, tools, llm, budget=None,
                      coverage="search", guidance=None, prior_draft=None,
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, should_cancel=None):
        return FakeResult()   # no .artifacts attribute -> getattr-default -> none

    with db.SessionLocal() as s:
        alchemy_exec.execute_alchemy_run(s, rid, Settings.from_env(),
                                         run_goal_fn=fake_run_goal)
        n = s.query(db.AlchemyArtifact).filter(
            db.AlchemyArtifact.run_id == rid).count()
        assert n == 0
