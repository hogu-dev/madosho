from __future__ import annotations

import json
import logging
import os
import signal
import sys

import procrastinate

from madosho_server import db, init_db, tasks
from madosho_server.settings import Settings, pg_conninfo


class _BenignAsyncTeardownFilter(logging.Filter):
    """Drop the one benign teardown record any_llm's *sync* completion() leaves behind.

    any_llm 1.17 runs each sync request in a throwaway event loop, then lets the
    provider's httpx AsyncClient be garbage-collected after that loop has already
    closed. httpx schedules aclose() on the dead loop, which raises
    RuntimeError('Event loop is closed'), and asyncio logs it as an unretrieved
    task exception. The request itself already succeeded - this is pure noise that
    clutters every worker LLM lane (research, vision, eval, contextual chunker).
    Match exactly that RuntimeError and nothing else. Remove if any_llm starts
    closing its client per call."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info
        err = exc[1] if exc else None
        return not (isinstance(err, RuntimeError) and "Event loop is closed" in str(err))


def run_init() -> None:
    """`madosho-init`: apply schemas, then exit (compose one-shot)."""
    init_db.init_database(Settings.from_env().database_url)


def make_worker_app() -> procrastinate.App:
    """The procrastinate app wired with the async connector for running jobs."""
    settings = Settings.from_env()
    db.configure_engine(settings.database_url)             # worker needs DB for status updates
    tasks.use_connector(procrastinate.PsycopgConnector(conninfo=pg_conninfo(settings.database_url)))
    return tasks.app


_DEFAULT_QUEUES = ["ingest", "ratings", "eval", "research", "alchemy"]


def worker_queues() -> list[str]:
    """Queues this worker drains. MADOSHO_WORKER_QUEUES is a comma list; blank
    or unset means all four. Lets an operator run queue-pinned workers (a
    research-only worker, an ingest-only worker) to avoid head-of-line blocking."""
    raw = os.environ.get("MADOSHO_WORKER_QUEUES", "")
    queues = [q.strip() for q in raw.split(",") if q.strip()]
    return queues or list(_DEFAULT_QUEUES)


def run_worker() -> None:
    """`madosho-worker`: run jobs one at a time; scale by adding containers."""
    logging.getLogger("asyncio").addFilter(_BenignAsyncTeardownFilter())
    worker_app = make_worker_app()
    # Best-effort startup sweep: fail any rows left stuck in a non-terminal state
    # from a previous SIGKILL/crash. A periodic in-loop sweep is deferred; this
    # startup sweep plus the SIGTERM handler covers the common cases.
    try:
        from madosho_server import sweeper
        with db.SessionLocal() as session:
            sweeper.sweep_stalled(session, Settings.from_env())
    except Exception:
        logging.getLogger("madosho_server.worker").exception("startup sweep failed")
    with worker_app.open():
        worker_app.run_worker(concurrency=1, queues=worker_queues())


def run_server() -> None:
    """`madosho-server`: serve the FastAPI control plane.

    Select the defer-only sync connector BEFORE serving; api.lifespan's
    tasks.app.open() then opens whatever connector use_connector last set."""
    import uvicorn
    settings = Settings.from_env()
    tasks.use_connector(
        procrastinate.SyncPsycopgConnector(conninfo=pg_conninfo(settings.database_url)))
    uvicorn.run("madosho_server.api:app", host="0.0.0.0", port=8000)


def run_query() -> None:
    """`madosho-query`: serve the FastAPI query plane (stateless, scale-out).

    Needs the DB (corpus configs + virtual models) but no queue connector —
    the query plane never enqueues. The app's lifespan configures the engine."""
    import uvicorn
    uvicorn.run("madosho_server.query_api:app", host="0.0.0.0", port=8001)


def _install_term_handler() -> None:
    """docker stop -> SIGTERM -> raise JobTerminated so the impl's existing
    `except Exception` marks its row failed and drops the partial collection
    before docker escalates to SIGKILL. A pure SIGKILL (past the grace period)
    skips this; the sweeper backstops that case."""
    from madosho_server.executor import JobTerminated

    def _term(_signum, _frame):
        raise JobTerminated("job container received SIGTERM")

    signal.signal(signal.SIGTERM, _term)


def run_job() -> None:
    """`madosho-run-job <task_name> <json-kwargs>`: run ONE job impl in this
    container, in-process. Bypasses the executor (no recursion) and configures
    its own DB engine since this is a fresh process."""
    from madosho_server import tasks
    logging.getLogger("asyncio").addFilter(_BenignAsyncTeardownFilter())
    name = sys.argv[1]
    kwargs = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    db.configure_engine(Settings.from_env().database_url)
    _install_term_handler()
    tasks._IMPLS[name](**kwargs)
