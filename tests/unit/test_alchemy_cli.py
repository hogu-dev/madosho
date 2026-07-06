"""Fast unit tests for the madosho-cli alchemy verb group.

Mirrors tests/unit/test_madosho_cli.py's FakeHttp fixture: urllib.request.urlopen
is stubbed to route canned JSON by URL substring (longest match first) and every
request is recorded so tests can assert method/url/body. No live server.
"""
from __future__ import annotations

import json
import urllib.request

import pytest

from madosho_cli import main as cli_main


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """Routes urlopen(req) by URL substring to a canned payload (or raises it).

    A route value may also be a zero-arg callable, invoked fresh on each match
    (used to simulate a run's status changing across successive polls).
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, object]] = []  # (method, url, json-body|None)

    def __call__(self, req, *a, **kw):
        url = req.full_url
        body = json.loads(req.data.decode()) if getattr(req, "data", None) else None
        self.calls.append((req.get_method(), url, body))
        for key in sorted(self.routes, key=len, reverse=True):  # most specific first
            if key in url:
                val = self.routes[key]
                if callable(val):
                    val = val()
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def fake_http(monkeypatch):
    def install(routes: dict) -> FakeHttp:
        fh = FakeHttp(routes)
        monkeypatch.setattr(urllib.request, "urlopen", fh)
        return fh

    return install


def _goal(**over):
    g = {"id": 1, "name": "find_vuln", "corpus_id": 3, "goal_type": "living-research",
         "spec": {"goal": "map vulns"}, "coverage": "search"}
    g.update(over)
    return g


def _run(**over):
    r = {"id": 9, "goal_id": 1, "version": 1, "status": "pending", "coverage": "search",
         "guidance": None, "based_on_version": None, "progress": {"phase": "pending"},
         "stop_reason": None, "usage": None, "is_final": False, "error": None}
    r.update(over)
    return r


def test_create_goal(fake_http, capsys):
    fake_http({
        "/corpora": [{"id": 3, "name": "secdocs", "config": {}}],
        "/alchemy/goals": _goal(),
    })
    rc = cli_main.main(["alchemy", "create", "find_vuln", "--corpus", "secdocs",
                        "--goal", "map vulns", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "find_vuln"


def test_create_goal_body_and_corpus_resolution(fake_http):
    fh = fake_http({
        "/corpora": [{"id": 3, "name": "secdocs", "config": {}}],
        "/alchemy/goals": _goal(),
    })
    cli_main.main(["alchemy", "create", "find_vuln", "--corpus", "secdocs",
                   "--goal", "map vulns", "--json"])
    method, url, body = fh.calls[-1]
    assert method == "POST" and url.endswith("/alchemy/goals")
    assert body == {"name": "find_vuln", "corpus_id": 3, "goal_type": "living-research",
                    "spec": {"goal": "map vulns"}, "coverage": "search"}


def test_create_goal_human_output(fake_http, capsys):
    fake_http({
        "/corpora": [{"id": 3, "name": "secdocs", "config": {}}],
        "/alchemy/goals": _goal(),
    })
    rc = cli_main.main(["alchemy", "create", "find_vuln", "--corpus", "secdocs",
                        "--goal", "map vulns"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "find_vuln" in out and "1" in out


def test_run_goal_no_wait(fake_http, capsys):
    fh = fake_http({
        "/alchemy/goals/find_vuln/runs": _run(version=1, status="pending"),
    })
    rc = cli_main.main(["alchemy", "run", "find_vuln", "--provider", "openai",
                        "--model", "m", "--no-wait", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == 1
    method, url, body = fh.calls[-1]
    assert method == "POST" and url.endswith("/alchemy/goals/find_vuln/runs")
    assert body["llm"] == {"provider": "openai", "model": "m"}
    # no CLI flags for these; core.alchemy_run supplies the same defaults the
    # API itself defaults to (budget_chars=100_000, max_rounds=8)
    assert body["budget_chars"] == 100_000 and body["max_rounds"] == 8
    assert "coverage" not in body and "guidance" not in body
    assert "max_llm_calls" not in body


def test_run_goal_passes_optional_fields(fake_http):
    fh = fake_http({
        "/alchemy/goals/find_vuln/runs": _run(version=2),
    })
    cli_main.main(["alchemy", "run", "find_vuln", "--provider", "openai", "--model", "m",
                   "--coverage", "search", "--guidance", "dig deeper",
                   "--based-on", "1", "--max-llm-calls", "5", "--no-wait", "--json"])
    _, _, body = fh.calls[-1]
    assert body["coverage"] == "search"
    assert body["guidance"] == "dig deeper"
    assert body["based_on_version"] == 1
    assert body["max_llm_calls"] == 5


def test_run_goal_waits_until_terminal(fake_http, capsys, monkeypatch):
    """Without --no-wait, the CLI polls status until done, printing progress."""
    calls = {"n": 0}

    def poll_response():
        calls["n"] += 1
        if calls["n"] < 2:
            return _run(version=1, status="running")
        return _run(version=1, status="done", usage={"llm_calls": 4})

    fake_http({
        "/alchemy/goals/find_vuln/runs/1": poll_response,
        "/alchemy/goals/find_vuln/runs": _run(version=1, status="pending"),
    })
    import madosho_cli.core as core_mod
    monkeypatch.setattr(core_mod.time, "sleep", lambda *_a, **_kw: None)
    rc = cli_main.main(["alchemy", "run", "find_vuln", "--provider", "openai",
                        "--model", "m", "--json"])
    assert rc == 0
    # _on_event_printer prints a progress line per poll to stdout regardless of
    # --json (same pre-existing behavior as cmd_upload_document/build_pipeline),
    # so the JSON result is the trailing blob, not the whole of stdout.
    printed = capsys.readouterr().out
    assert "[running]" in printed and "[done]" in printed
    # the JSON dump is the only unindented "{" line (progress lines are
    # indented "  [status] ..."), so split there rather than on the first "{".
    json_start = printed.rindex("\n{\n") + 1
    out = json.loads(printed[json_start:])
    assert out["status"] == "done"
    assert calls["n"] >= 2


def test_wait_for_alchemy_run_times_out(fake_http, monkeypatch):
    """The wait loop measures elapsed wall time (monotonic), not sleep counts,
    so slow polls cannot silently stretch the timeout budget."""
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="running"),
    })
    import madosho_cli.core as core_mod
    from madosho_cli import http as cli_http
    clock = {"now": 0.0}
    monkeypatch.setattr(core_mod.time, "monotonic", lambda: clock["now"])
    # each poll's sleep advances the fake clock; the run never leaves "running"
    monkeypatch.setattr(core_mod.time, "sleep",
                        lambda s: clock.__setitem__("now", clock["now"] + s))
    with pytest.raises(cli_http.CliError, match="timed out"):
        core_mod.wait_for_alchemy_run("find_vuln", 1, on_event=lambda _e: None,
                                      interval=1.0, timeout=3.0)


def test_run_goal_failed_exits_nonzero(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="failed",
                                                error="boom"),
        "/alchemy/goals/find_vuln/runs": _run(version=1, status="pending"),
    })
    rc = cli_main.main(["alchemy", "run", "find_vuln", "--provider", "openai",
                        "--model", "m", "--json"])
    assert rc == 1


def test_status_latest_version(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/2": _run(version=2, status="running"),
        "/alchemy/goals/find_vuln/runs": [_run(version=2, status="running"),
                                          _run(version=1, status="done")],
    })
    rc = cli_main.main(["alchemy", "status", "find_vuln", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == 2


def test_status_explicit_run(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="done"),
    })
    rc = cli_main.main(["alchemy", "status", "find_vuln", "--run", "1", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == 1


def test_status_no_runs_errors(fake_http, capsys):
    fake_http({"/alchemy/goals/find_vuln/runs": []})
    rc = cli_main.main(["alchemy", "status", "find_vuln", "--json"])
    assert rc == 1
    assert "no runs" in capsys.readouterr().err


def test_export_writes_markdown(fake_http, tmp_path, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="done",
                                                draft_markdown="# Draft\nbody",
                                                citations=[]),
        "/alchemy/goals/find_vuln/runs": [_run(version=1, status="done")],
    })
    out_file = tmp_path / "r.md"
    rc = cli_main.main(["alchemy", "export", "find_vuln", "--run", "1",
                        "-o", str(out_file)])
    assert rc == 0
    assert out_file.read_text().startswith("# Draft")
    assert "wrote" in capsys.readouterr().out


def test_export_default_filename(fake_http, tmp_path, monkeypatch, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="done",
                                                draft_markdown="hello"),
        "/alchemy/goals/find_vuln/runs": [_run(version=1, status="done")],
    })
    monkeypatch.chdir(tmp_path)
    rc = cli_main.main(["alchemy", "export", "find_vuln"])
    assert rc == 0
    assert (tmp_path / "find_vuln-v1.md").read_text() == "hello"


def test_export_no_runs_errors(fake_http, capsys):
    fake_http({"/alchemy/goals/find_vuln/runs": []})
    rc = cli_main.main(["alchemy", "export", "find_vuln"])
    assert rc == 1
    assert "no runs" in capsys.readouterr().err


def test_finalize(fake_http, capsys):
    fh = fake_http({
        "/alchemy/goals/find_vuln/finalize": _run(version=2, status="done",
                                                   is_final=True),
    })
    rc = cli_main.main(["alchemy", "finalize", "find_vuln", "--run", "2", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["is_final"] is True
    method, url, body = fh.calls[-1]
    assert method == "POST" and body == {"version": 2}


def test_list_goals(fake_http, capsys):
    fake_http({"/alchemy/goals": [_goal(), _goal(id=2, name="other", corpus_id=4)]})
    rc = cli_main.main(["alchemy", "list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in out] == ["find_vuln", "other"]


def test_list_goals_human(fake_http, capsys):
    fake_http({"/alchemy/goals": [_goal()]})
    rc = cli_main.main(["alchemy", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "find_vuln" in out and "3" in out


def test_runs_for_goal(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs": [_run(version=2, status="running"),
                                          _run(version=1, status="done", is_final=True)],
    })
    rc = cli_main.main(["alchemy", "runs", "find_vuln", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["version"] for r in out] == [2, 1]


def test_runs_for_goal_human(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs": [_run(version=1, status="done", is_final=True)],
    })
    rc = cli_main.main(["alchemy", "runs", "find_vuln"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "v1" in out and "done" in out and "FINAL" in out


def test_cancel_run(fake_http, capsys):
    fh = fake_http({"/alchemy/runs/9/cancel": {"status": "cancelled"}})
    rc = cli_main.main(["alchemy", "cancel", "9", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "cancelled"
    method, url, _ = fh.calls[-1]
    assert method == "POST" and url.endswith("/alchemy/runs/9/cancel")
