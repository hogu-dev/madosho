from madosho_server.executor import InProcessExecutor, resolve_executor
from madosho_server.settings import Settings


def test_inprocess_executor_calls_the_named_impl():
    seen = {}
    impls = {"do_thing": lambda **kw: seen.update(kw)}
    InProcessExecutor(impls).run("do_thing", {"x": 1, "y": 2})
    assert seen == {"x": 1, "y": 2}


def test_resolve_defaults_to_inprocess(monkeypatch):
    monkeypatch.delenv("MADOSHO_JOB_EXECUTOR", raising=False)
    ex = resolve_executor("ingest", Settings.from_env(), impls={})
    assert isinstance(ex, InProcessExecutor)
