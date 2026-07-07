"""Alchemy worker logic: the ONLY adapter between madosho_server and the
alchemy package (which drives research_agent). Resolves the prior draft for
guidance reruns, builds the real tool/LLM providers, runs the goal, and
writes the GoalRunResult back onto the alchemy_run row. Mirrors research.py:
a run_goal_fn dependency is the test seam. It imports alchemy; alchemy imports
nothing from here.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass

from madosho_server import db
from madosho_server.tasks import _finish, _is_alchemy_cancelled

logger = logging.getLogger(__name__)


def _make_cancel_check(alchemy_run_id):
    """Poll the row for a cancelled status; passed as should_cancel into the
    loop so a run stops cooperatively at a round boundary."""
    def should_cancel():
        with db.SessionLocal() as s:
            s.expire_all()
            r = s.get(db.AlchemyRun, alchemy_run_id)
            return r is not None and r.status == "cancelled"
    return should_cancel


def _make_progress_writer(alchemy_run_id):
    """Persist orchestrator progress events onto the run row. Uses its own
    short session (same pattern as the cancel check) so the adapter's main
    session is never committed mid-run; guarded on status so a late event
    from a cancelled run cannot clobber a terminal row."""
    def on_progress(progress: dict):
        with db.SessionLocal() as s:
            r = s.get(db.AlchemyRun, alchemy_run_id)
            if r is not None and r.status == "running":
                r.progress = dict(progress)
                s.commit()
    return on_progress


def _default_run_goal(goal_type, spec, *, corpus, settings, guidance,
                      prior_draft, provider, model, budget_chars, max_rounds,
                      max_llm_calls, alchemy_run_id, coverage="search",
                      prior_sections=None, prior_ledger=None,
                      on_progress=None, tools=None, llm=None,
                      should_cancel=None):
    """Real path: build the CLI tool provider + any_llm client from madosho's
    creds and run the alchemy engine. Lazily imported so unit tests that inject
    a fake run_goal_fn never touch research_agent or subprocesses.

    tools/llm/should_cancel are accepted-and-ignored: the `runner` wrapper in
    execute_alchemy_run calls both the real and fake paths through the same
    **kw shape (it does not know which one it holds), so this always receives
    the placeholders execute_alchemy_run hands the fake seam (tools=None,
    llm=None, should_cancel=<the real cancel check>). The real path builds its
    own tool/llm providers below and its own should_cancel closure at return
    time, so all three are discarded here. coverage/prior_sections/
    prior_ledger/on_progress are REAL and forwarded straight through to the
    engine."""
    import research_agent
    import alchemy
    endpoint = research_agent.LlmEndpoint(
        provider=provider, model=model,
        api_key=settings.llm_api_key, api_base=settings.llm_api_base)
    tools = research_agent.CliToolProvider(["python", "-m", "madosho_cli"])
    llm = research_agent.AnyLlmClient(endpoint)
    budget = research_agent.RunBudget(max_context_chars=budget_chars,
                                      max_rounds=max_rounds)
    return alchemy.run_goal(goal_type, spec, corpus=corpus, tools=tools,
                            llm=llm, budget=budget, coverage=coverage,
                            guidance=guidance,
                            prior_draft=prior_draft,
                            prior_sections=prior_sections,
                            prior_ledger=prior_ledger,
                            max_llm_calls=max_llm_calls,
                            should_cancel=_make_cancel_check(alchemy_run_id),
                            on_progress=on_progress)


def _prior_draft_for(session, goal_id, based_on_version):
    if based_on_version is None:
        return None
    prior = session.query(db.AlchemyRun).filter(
        db.AlchemyRun.goal_id == goal_id,
        db.AlchemyRun.version == based_on_version).first()
    return prior.draft_markdown if prior is not None else None


def _prior_sections_for(session, goal_id, based_on_version):
    if based_on_version is None:
        return None
    prior = session.query(db.AlchemyRun).filter(
        db.AlchemyRun.goal_id == goal_id,
        db.AlchemyRun.version == based_on_version).first()
    return prior.sections if prior is not None else None


def _prior_ledger_for(session, goal_id, based_on_version):
    if based_on_version is None:
        return None
    prior = session.query(db.AlchemyRun).filter(
        db.AlchemyRun.goal_id == goal_id,
        db.AlchemyRun.version == based_on_version).first()
    return prior.ledger if prior is not None else None


def _usage_dict(usage):
    if usage is None:
        return {}
    if is_dataclass(usage):
        return asdict(usage)
    return {"llm_calls": getattr(usage, "llm_calls", 0),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0)}


def _section_dicts(result):
    """SectionResult dataclasses (real path) or plain dicts (test fakes) ->
    JSON-ready dicts. getattr-with-default keeps stage-A-shaped results
    (no sections attribute) working unchanged."""
    out = []
    for s in getattr(result, "sections", None) or []:
        out.append(asdict(s) if is_dataclass(s) else dict(s))
    return out


def execute_alchemy_run(session, alchemy_run_id: int, settings,
                        *, run_goal_fn=None) -> None:
    """Run one alchemy_run end to end. run_goal_fn defaults to the real path;
    a fake returns a canned GoalRunResult so this is unit-testable with no LLM,
    CLI, or subprocess."""
    run = session.get(db.AlchemyRun, alchemy_run_id)
    if run is None:
        return
    goal = session.get(db.AlchemyGoal, run.goal_id)
    corpus = session.get(db.Corpus, goal.corpus_id)
    cfg = run.config or {}
    llm_cfg = cfg.get("llm") or {}
    provider, model = llm_cfg.get("provider"), llm_cfg.get("model")
    if not provider or not model:
        return _finish(session, run, "failed",
                       error="no LLM provider/model configured for this run")

    run.status = "running"
    run.progress = {"phase": "running"}
    session.commit()

    prior_draft = _prior_draft_for(session, goal.id, run.based_on_version)
    prior_sections = _prior_sections_for(session, goal.id, run.based_on_version)
    # fresh_coverage opts a rerun OUT of the union-of-chain guarantee (the
    # spec's "unless guidance says to" knob, made explicit): the run then
    # re-consults from scratch instead of inheriting v(N-1)'s ledger.
    prior_ledger = (None if cfg.get("fresh_coverage")
                    else _prior_ledger_for(session, goal.id, run.based_on_version))
    runner = run_goal_fn or (lambda goal_type, spec, **kw: _default_run_goal(
        goal_type, spec, settings=settings, provider=provider, model=model,
        budget_chars=cfg.get("budget_chars", 100_000),
        max_rounds=cfg.get("max_rounds", 8),
        max_llm_calls=cfg.get("max_llm_calls"),
        alchemy_run_id=alchemy_run_id, **kw))
    try:
        result = runner(goal.goal_type, goal.spec, corpus=corpus.name,
                        tools=None, llm=None, guidance=run.guidance,
                        coverage=run.coverage or "search",
                        prior_draft=prior_draft,
                        prior_sections=prior_sections,
                        prior_ledger=prior_ledger,
                        on_progress=_make_progress_writer(alchemy_run_id),
                        should_cancel=_make_cancel_check(alchemy_run_id))
        run.draft_markdown = result.markdown
        run.citations = [asdict(c) if is_dataclass(c) else vars(c)
                         for c in result.citations]
        run.run_log = list(result.run_log)
        run.sections = _section_dicts(result)
        run.stop_reason = result.stop_reason
        run.usage = _usage_dict(result.usage)
        run.ledger = getattr(result, "ledger", None) or {}
        run.progress = {"phase": "done"}
        session.flush()  # persist before the cancel re-read
        if _is_alchemy_cancelled(session, alchemy_run_id):
            return _finish(session, run, "cancelled")
        if result.stop_reason == "failed":
            # a report unit crashed: the engine already caught it and landed
            # every section that survived (draft/citations/sections/usage are
            # persisted above), so we keep the partial result but flag the run
            # failed and surface the first failing section's note as the error.
            # Mirrors how "cancelled" maps below - the living-research path
            # never returns "failed" (its exceptions propagate to the handler).
            note = next((s.get("note") for s in (run.sections or [])
                         if (s.get("note") or "").startswith("unit failed")),
                        None)
            return _finish(session, run, "failed", error=note)
        _finish(session, run, "done")
    except Exception as e:
        logger.exception("alchemy run %s failed", alchemy_run_id)
        session.rollback()
        run = session.get(db.AlchemyRun, alchemy_run_id)
        _finish(session, run, "failed", error=str(e))
