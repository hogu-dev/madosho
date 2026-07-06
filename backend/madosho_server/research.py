"""Research worker logic: compose the steering prompt, build the agent, run it.

madosho is research_agent's first consumer. This module is the *only* adapter:
it composes the per-run prompt (source/target steering, since research_agent.run
takes only a prompt + tools + llm + budget), builds a CliToolProvider over the
madosho CLI and an AnyLlmClient from madosho's configured creds, runs the loop,
and writes the Report back to the research_run row. It imports research_agent;
research_agent imports nothing from here.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from madosho_server import db
from madosho_server.tasks import _finish, _is_research_cancelled

logger = logging.getLogger(__name__)


def compose_research_prompt(question: str, corpus_name: str, source: str,
                            document_ids: list[int], budget_chars: int) -> str:
    """Build the prompt the agent runs on. The agent discovers its tools from the
    CLI manifest; this prompt tells it WHICH corpus to search (by name) and HOW to
    favour the chosen source. Target documents are passed by id for get-doc."""
    lines = [f"Research question: {question}", ""]
    lines.append(f"The corpus to research is named '{corpus_name}'. "
                 f"Pass this exact name as the `corpus` argument to the search and "
                 f"list-documents tools.")
    if source == "whole-text":
        if document_ids:
            ids = ", ".join(str(i) for i in document_ids)
            lines.append(
                f"Read these documents whole using the get-doc tool: document ids "
                f"{ids}. If their combined text exceeds the context budget "
                f"({budget_chars} characters), fall back to the search tool over "
                f"the corpus and note the fallback in your report.")
        else:
            lines.append(
                f"Prefer reading whole documents with get-doc (use list-documents "
                f"to find their ids). If the documents exceed the context budget "
                f"({budget_chars} characters), fall back to the search tool and note "
                f"the fallback in your report.")
    else:  # "rag"
        lines.append(
            "Use the search tool (RAG retrieval) to gather evidence: issue focused "
            "queries, read the chunks, and refine.")
        if document_ids:
            ids = ", ".join(str(i) for i in document_ids)
            lines.append(f"Focus on what these documents say (ids {ids}); search is "
                         f"corpus-wide, so weight hits from those documents.")
    return "\n".join(lines)


def _make_cancel_check(research_run_id):
    """Return a closure that polls the DB row for a cancelled status.
    Passed as should_cancel= into research_agent.run so the loop can stop
    cooperatively at the next round boundary without finishing the full budget."""
    def should_cancel():
        with db.SessionLocal() as s:
            s.expire_all()
            r = s.get(db.ResearchRun, research_run_id)
            return r is not None and r.status == "cancelled"
    return should_cancel


def _default_run_agent(prompt: str, settings, provider: str, model: str, *,
                       budget_chars: int, max_rounds: int, research_run_id: int):
    """The real agent path: build the CLI tool provider + an any_llm-backed client
    from madosho's configured creds, and run the loop. Imported lazily so the unit
    tests (which inject a fake run_agent) never need research_agent or subprocesses."""
    import research_agent
    endpoint = research_agent.LlmEndpoint(
        provider=provider, model=model,
        api_key=settings.llm_api_key, api_base=settings.llm_api_base)
    tools = research_agent.CliToolProvider(["python", "-m", "madosho_cli"])
    budget = research_agent.RunBudget(max_context_chars=budget_chars, max_rounds=max_rounds)
    return research_agent.run(prompt, tools=tools,
                              llm=research_agent.AnyLlmClient(endpoint), budget=budget,
                              should_cancel=_make_cancel_check(research_run_id))


def execute_research(session, research_run_id: int, settings, *, run_agent=None) -> None:
    """Run one research_run end to end. The run_agent dep (defaults to the real
    _default_run_agent) is the test seam - a fake returns a canned Report so this
    is unit-testable without an LLM, the CLI, or a subprocess."""
    run = session.get(db.ResearchRun, research_run_id)
    if run is None:
        return
    corpus = session.get(db.Corpus, run.corpus_id)
    cfg = run.config or {}
    llm_cfg = cfg.get("llm") or {}
    provider, model = llm_cfg.get("provider"), llm_cfg.get("model")
    if not provider or not model:
        return _finish(session, run, "failed",
                       error="no LLM provider/model configured for this run")

    run.status = "running"
    run.progress = {"phase": "researching"}
    session.commit()

    runner = run_agent or _default_run_agent
    try:
        prompt = compose_research_prompt(
            run.prompt, corpus.name, cfg.get("source", "rag"),
            cfg.get("document_ids") or [], cfg.get("budget_chars", 100_000))
        report = runner(prompt, settings, provider, model,
                        budget_chars=cfg.get("budget_chars", 100_000),
                        max_rounds=cfg.get("max_rounds", 8),
                        research_run_id=research_run_id)
        run.report_markdown = report.markdown
        run.citations = [asdict(c) if hasattr(type(c), "__dataclass_fields__")
                         else vars(c) for c in report.citations]
        run.run_log = list(report.run_log)
        run.stop_reason = report.stop_reason
        run.progress = {"phase": "done"}
        session.flush()  # persist report/citations/log before the cancel-check re-read
        if _is_research_cancelled(session, research_run_id):
            return _finish(session, run, "cancelled")
        _finish(session, run, "done")
    except Exception as e:
        logger.exception("research run %s failed", research_run_id)
        session.rollback()
        run = session.get(db.ResearchRun, research_run_id)
        _finish(session, run, "failed", error=str(e))
