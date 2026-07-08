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


def _report_run(**over):
    r = _run(version=1, status="done",
             draft_markdown="# Vuln report\n\n## Summary\n\nAll clear.\n")
    r["sections"] = [
        {"key": "summary", "title": "Summary", "content": "All clear.",
         "filled": True, "note": "",
         "confidence": {"level": "high", "distinct_docs": 2, "citations": 3}},
        {"key": "detail", "title": "Detail", "content": "",
         "filled": False, "note": "skipped: llm call cap",
         "confidence": {"level": "low", "distinct_docs": 0, "citations": 0}},
    ]
    r["citations"] = [{"n": 1, "document_id": 7, "citation": "doc7"}]
    r.update(over)
    return r


def test_export_json_writes_structured(fake_http, tmp_path, capsys):
    run = _report_run()
    fake_http({
        "/alchemy/goals/vuln_report/runs/1": run,
        "/alchemy/goals/vuln_report/runs": [run],
    })
    out_file = tmp_path / "r.json"
    rc = cli_main.main(["alchemy", "export", "vuln_report", "--run", "1",
                        "--format", "json", "-o", str(out_file)])
    assert rc == 0
    doc = json.loads(out_file.read_text())
    assert doc["title"] == "Vuln report"          # from the draft's first '# '
    assert [s["key"] for s in doc["sections"]] == ["summary", "detail"]
    assert doc["sections"][0]["filled"] is True
    assert doc["sections"][0]["confidence"]["level"] == "high"
    assert doc["sections"][1]["note"] == "skipped: llm call cap"
    assert doc["citations"][0]["document_id"] == 7
    assert "wrote" in capsys.readouterr().out


def test_export_json_default_filename(fake_http, tmp_path, monkeypatch):
    run = _report_run(version=2)
    fake_http({
        "/alchemy/goals/find_vuln/runs/2": run,
        "/alchemy/goals/find_vuln/runs": [run],
    })
    monkeypatch.chdir(tmp_path)
    rc = cli_main.main(["alchemy", "export", "find_vuln", "--format", "json"])
    assert rc == 0
    doc = json.loads((tmp_path / "find_vuln-v2.json").read_text())
    assert doc["title"] == "Vuln report"


def test_export_md_is_still_default(fake_http, tmp_path, capsys):
    # no --format -> markdown, byte-for-byte the prior behavior
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(version=1, status="done",
                                                draft_markdown="# Draft\nbody"),
        "/alchemy/goals/find_vuln/runs": [_run(version=1, status="done")],
    })
    out_file = tmp_path / "r.md"
    rc = cli_main.main(["alchemy", "export", "find_vuln", "--run", "1",
                        "-o", str(out_file)])
    assert rc == 0
    assert out_file.read_text().startswith("# Draft")
    assert "wrote" in capsys.readouterr().out


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


def test_create_report_goal_sends_template(fake_http, tmp_path):
    spec_file = tmp_path / "t.md"
    spec_file.write_text("# R\n\n## Summary\n\nshort.\n", encoding="utf-8")
    fh = fake_http({
        "/corpora": [{"id": 3, "name": "secdocs", "config": {}}],
        "/alchemy/goals": _goal(goal_type="report"),
    })
    rc = cli_main.main(["alchemy", "create", "vuln_report", "--corpus",
                        "secdocs", "--type", "report", "--spec",
                        str(spec_file), "--json"])
    assert rc == 0
    method, url, body = fh.calls[-1]
    assert method == "POST" and url.endswith("/alchemy/goals")
    assert body["goal_type"] == "report"
    assert body["spec"] == {"template": "# R\n\n## Summary\n\nshort.\n"}


def test_create_report_requires_spec(fake_http, capsys):
    fake_http({})
    rc = cli_main.main(["alchemy", "create", "r", "--corpus", "c",
                        "--type", "report"])
    assert rc != 0
    assert "--spec" in capsys.readouterr().err


def test_create_living_research_requires_goal(fake_http, capsys):
    fake_http({})
    rc = cli_main.main(["alchemy", "create", "r", "--corpus", "c"])
    assert rc != 0
    assert "--goal" in capsys.readouterr().err


def test_create_report_with_goal_conflicts(fake_http, tmp_path, capsys):
    # --goal is meaningless for a report (its goal is the template preamble);
    # the CLI rejects the combination instead of silently dropping --goal
    spec_file = tmp_path / "t.md"
    spec_file.write_text("# R\n\n## S\n\nx.\n", encoding="utf-8")
    fake_http({})
    rc = cli_main.main(["alchemy", "create", "r", "--corpus", "c",
                        "--type", "report", "--spec", str(spec_file),
                        "--goal", "stray goal"])
    assert rc != 0
    assert "--goal" in capsys.readouterr().err


def test_create_living_research_with_spec_conflicts(fake_http, tmp_path, capsys):
    # --spec is report-only; living-research must reject it, not ignore it
    spec_file = tmp_path / "t.md"
    spec_file.write_text("# R\n\n## S\n\nx.\n", encoding="utf-8")
    fake_http({})
    rc = cli_main.main(["alchemy", "create", "r", "--corpus", "c",
                        "--goal", "map vulns", "--spec", str(spec_file)])
    assert rc != 0
    assert "--spec" in capsys.readouterr().err


def test_status_renders_section_table(fake_http, capsys):
    run = _run(status="done", version=2, progress={"phase": "done"})
    run["sections"] = [
        {"key": "summary", "title": "Summary", "filled": True, "note": "",
         "confidence": {"level": "high", "distinct_docs": 3, "citations": 5}},
        {"key": "june", "title": "June incidents", "filled": False,
         "note": "skipped: llm call cap",
         "confidence": {"level": "low", "distinct_docs": 0, "citations": 0}},
    ]
    fake_http({
        "/alchemy/goals/vuln_report/runs/2": run,
        "/alchemy/goals/vuln_report/runs": [run],
    })
    rc = cli_main.main(["alchemy", "status", "vuln_report"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Summary" in out and "high" in out
    assert "3 docs" in out and "5 cites" in out
    assert "not filled: skipped: llm call cap" in out


def test_status_without_sections_unchanged(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(status="running",
                                                progress={"phase": "running"}),
        "/alchemy/goals/find_vuln/runs": [_run(status="running")],
    })
    rc = cli_main.main(["alchemy", "status", "find_vuln"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "find_vuln v1: running" in out


def test_alchemy_run_passes_coverage_and_fresh_flag(fake_http):
    fh = fake_http({
        "/alchemy/goals/find_vuln/runs": _run(version=1, status="pending"),
    })
    cli_main.main(["alchemy", "run", "find_vuln", "--provider", "openai",
                   "--model", "m", "--coverage", "exhaustive",
                   "--fresh-coverage", "--no-wait", "--json"])
    _, url, body = fh.calls[-1]
    assert url.endswith("/alchemy/goals/find_vuln/runs")
    assert body["coverage"] == "exhaustive"
    assert body["fresh_coverage"] is True


def test_alchemy_create_accepts_full_coverage(fake_http):
    fh = fake_http({
        "/corpora": [{"id": 3, "name": "secdocs", "config": {}}],
        "/alchemy/goals": _goal(coverage="full"),
    })
    cli_main.main(["alchemy", "create", "find_vuln", "--corpus", "secdocs",
                   "--goal", "map vulns", "--coverage", "full", "--json"])
    _, url, body = fh.calls[-1]
    assert url.endswith("/alchemy/goals")
    assert body["coverage"] == "full"


def test_alchemy_status_prints_coverage_summary(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(
            version=1, status="done", progress={"phase": "done"},
            sections=[], usage={"llm_calls": 3},
            ledger={"summary": "coverage full: consulted 2/2 docs"}),
    })
    rc = cli_main.main(["alchemy", "status", "find_vuln", "--run", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "coverage full: consulted 2/2 docs" in out


def test_alchemy_artifacts_lists(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/2/artifacts": [
            {"id": 1, "kind": "digest", "key": "doc-1", "document_id": None,
             "payload": {"filename": "a.txt", "text": "hello"},
             "created_at": "2026-07-07T00:00:00"},
            {"id": 2, "kind": "handoff", "key": "body-h1", "document_id": None,
             "payload": {"attempt": 1, "docs_covered": [1, 2],
                         "partial_chars": 40},
             "created_at": "2026-07-07T00:00:01"},
        ],
    })
    rc = cli_main.main(["alchemy", "artifacts", "find_vuln", "--run", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "digest" in out and "doc-1" in out and "a.txt" in out
    assert "handoff" in out and "body-h1" in out


def test_alchemy_artifacts_json(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1/artifacts": [
            {"id": 1, "kind": "digest", "key": "doc-1", "document_id": None,
             "payload": {}, "created_at": "2026-07-07T00:00:00"},
        ],
    })
    rc = cli_main.main(["alchemy", "artifacts", "find_vuln", "--run", "1", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["kind"] == "digest"


def test_alchemy_artifacts_empty(fake_http, capsys):
    fake_http({"/alchemy/goals/find_vuln/runs/3/artifacts": []})
    rc = cli_main.main(["alchemy", "artifacts", "find_vuln", "--run", "3"])
    assert rc == 0
    assert "no artifacts" in capsys.readouterr().out


def test_alchemy_status_shows_artifact_counts(fake_http, capsys):
    fake_http({
        "/alchemy/goals/find_vuln/runs/1": _run(
            version=1, status="done", progress={"phase": "done"},
            artifact_counts={"digest": 2, "handoff": 1}),
    })
    rc = cli_main.main(["alchemy", "status", "find_vuln", "--run", "1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "artifacts:" in out
    assert "2 digest" in out and "1 handoff" in out


def test_alchemy_ingest_posts_to_run_ingest(fake_http):
    fh = fake_http({
        "/alchemy/goals/find_vuln/runs/2/ingest":
            {"id": 42, "filename": "find_vuln-v2.md", "status": "received",
             "origin": "generated", "origin_label": "[generated: find_vuln v2]"},
    })
    rc = cli_main.main(["alchemy", "ingest", "find_vuln", "--run", "2",
                        "--corpus", "reports", "--json"])
    assert rc == 0
    method, url, body = fh.calls[-1]
    assert method == "POST"
    assert url.endswith("/alchemy/goals/find_vuln/runs/2/ingest")
    assert body == {"corpus": "reports"}


def test_alchemy_ingest_defaults_to_latest_run(fake_http):
    fh = fake_http({
        # runs list (newest first) resolves the latest version
        "/alchemy/goals/find_vuln/runs": [_run(version=3, status="done")],
        "/alchemy/goals/find_vuln/runs/3/ingest":
            {"id": 7, "filename": "find_vuln-v3.md", "status": "received",
             "origin": "generated"},
    })
    rc = cli_main.main(["alchemy", "ingest", "find_vuln", "--json"])
    assert rc == 0
    _, url, body = fh.calls[-1]
    assert url.endswith("/alchemy/goals/find_vuln/runs/3/ingest")
    assert body == {}                       # no --corpus -> empty body


def test_alchemy_finalize_forwards_ingest_flag(fake_http):
    fh = fake_http({
        "/alchemy/goals/find_vuln/finalize":
            _run(version=1, status="done", is_final=True,
                 ingested_document_id=9),
    })
    cli_main.main(["alchemy", "finalize", "find_vuln", "--run", "1",
                   "--ingest", "--json"])
    _, url, body = fh.calls[-1]
    assert url.endswith("/alchemy/goals/find_vuln/finalize")
    assert body == {"version": 1, "ingest": True}
