"""the server-side research trigger - corpus resolve, launch body, poll loop.
Transports are injected so the flow is exercised without a network."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_trigger():
    path = ROOT / "skills" / "research_trigger.py"
    spec = importlib.util.spec_from_file_location("research_trigger", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt = _load_trigger()


def test_resolve_corpus_id_finds_by_name():
    get = lambda url: [{"id": 1, "name": "a"}, {"id": 7, "name": "verify"}]
    assert rt.resolve_corpus_id("verify", control_base="http://c", get_json=get) == 7


def test_resolve_corpus_id_missing_raises():
    get = lambda url: [{"id": 1, "name": "a"}]
    with pytest.raises(SystemExit):
        rt.resolve_corpus_id("ghost", control_base="http://c", get_json=get)


def test_launch_posts_research_launch_body():
    seen = {}

    def post(url, payload):
        seen["url"] = url
        seen["payload"] = payload
        return {"id": 42, "status": "pending"}

    run_id = rt.launch(7, "what are the terms?", {"provider": "openai", "model": "m"},
                       control_base="http://c", post_json=post)
    assert run_id == 42
    assert seen["url"] == "http://c/corpora/7/research"
    assert seen["payload"]["prompt"] == "what are the terms?"
    assert seen["payload"]["source"] == "rag"
    assert seen["payload"]["llm"] == {"provider": "openai", "model": "m"}
    assert seen["payload"]["max_rounds"] == 8
    assert seen["payload"]["budget_chars"] == 100_000
    assert seen["payload"]["document_ids"] == []


def test_poll_returns_when_status_leaves_running():
    seq = iter([{"status": "pending"}, {"status": "running"},
                {"status": "done", "report_markdown": "# R", "citations": []}])
    get = lambda url: next(seq)
    run = rt.poll(7, 42, control_base="http://c", get_json=get,
                  sleep=lambda _s: None, interval=0.0, timeout=10.0)
    assert run["status"] == "done"
    assert run["report_markdown"] == "# R"


def test_poll_times_out_promptly():
    calls = {"n": 0}

    def get(url):
        calls["n"] += 1
        return {"status": "running"}

    with pytest.raises(SystemExit):
        rt.poll(7, 42, control_base="http://c", get_json=get,
                sleep=lambda _s: None, interval=2.0, timeout=0.5)
    # timeout (0.5) < interval (2.0): give up after the first poll, do not sleep past it
    assert calls["n"] == 1


def test_main_prints_real_report_shape(monkeypatch, capsys):
    # the real GET /corpora/{id}/research/{run_id} shape: report_markdown + citations top-level
    monkeypatch.setattr(rt, "resolve_corpus_id", lambda name, **kw: 7)
    monkeypatch.setattr(rt, "launch", lambda *a, **kw: 42)
    monkeypatch.setattr(rt, "poll", lambda *a, **kw: {
        "status": "done",
        "report_markdown": "# Findings\n\nThe answer is 42.",
        "citations": [{"citation": "a.pdf p.1"}, {"citation": "a.pdf p.2"}],
    })
    rc = rt.main(["--corpus", "verify", "--prompt", "q",
                  "--provider", "openai", "--model", "m"])
    out = capsys.readouterr()
    assert rc == 0
    assert "# Findings" in out.out and "The answer is 42." in out.out
    assert "2 citation(s)" in out.err
