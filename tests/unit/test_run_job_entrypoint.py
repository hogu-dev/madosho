import os
import signal

import pytest

from madosho_server import entrypoints, tasks
from madosho_server.executor import JobTerminated


def test_run_job_calls_the_named_impl(monkeypatch):
    seen = {}
    monkeypatch.setitem(tasks._IMPLS, "_probe", lambda **kw: seen.update(kw))
    monkeypatch.setattr("sys.argv", ["madosho-run-job", "_probe", '{"document_id": 7}'])
    monkeypatch.setattr(entrypoints.db, "configure_engine", lambda *a, **k: None)
    entrypoints.run_job()
    assert seen == {"document_id": 7}


def test_term_handler_raises_job_terminated():
    entrypoints._install_term_handler()
    handler = signal.getsignal(signal.SIGTERM)
    with pytest.raises(JobTerminated):
        handler(signal.SIGTERM, None)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)   # restore
