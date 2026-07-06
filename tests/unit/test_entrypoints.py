import logging

from madosho_server import entrypoints


def _record(exc):
    return logging.LogRecord("asyncio", logging.ERROR, __file__, 0,
                             "Task exception was never retrieved", (),
                             (type(exc), exc, None) if exc else None)


def test_teardown_filter_drops_only_closed_loop_runtimeerror():
    f = entrypoints._BenignAsyncTeardownFilter()
    # the benign any_llm teardown noise -> dropped
    assert f.filter(_record(RuntimeError("Event loop is closed"))) is False
    # a different RuntimeError -> kept
    assert f.filter(_record(RuntimeError("something real broke"))) is True
    # a non-RuntimeError exception -> kept
    assert f.filter(_record(ValueError("Event loop is closed"))) is True
    # an ordinary record with no exc_info -> kept
    assert f.filter(_record(None)) is True


def test_make_worker_app_registers_ingest_task(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    worker_app = entrypoints.make_worker_app()
    assert "ingest_document" in worker_app.tasks


def test_run_entrypoints_are_callable():
    assert callable(entrypoints.run_server)
    assert callable(entrypoints.run_worker)
    assert callable(entrypoints.run_init)
    assert callable(entrypoints.run_query)
