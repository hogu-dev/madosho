"""The standalone CLI: arg parsing + wiring. The actual run() is monkeypatched so
these stay fast (the real end-to-end path is the slow compose e2e in Task 8)."""
from __future__ import annotations

import research_agent.cli as cli
from research_agent.types import Citation, Report


def test_missing_provider_returns_2(capsys, monkeypatch):
    monkeypatch.delenv("RESEARCH_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("RESEARCH_AGENT_MODEL", raising=False)
    rc = cli.main(["run", "--prompt", "q", "--model", "m"])
    assert rc == 2
    assert "provider" in capsys.readouterr().err.lower()


def test_wires_tools_and_endpoint_then_runs(capsys, monkeypatch, tmp_path):
    captured = {}

    def fake_run(prompt, *, tools, llm, autonomous_md=None, budget=None):
        captured["prompt"] = prompt
        captured["cli_argv"] = tools.cli_argv
        captured["provider"] = llm.endpoint.provider
        captured["model"] = llm.endpoint.model
        captured["api_base"] = llm.endpoint.api_base
        captured["budget"] = (budget.max_context_chars, budget.max_rounds)
        return Report(markdown="# Hello", citations=[
            Citation(document_id=2, pipeline_id=3, pipeline="p", position=1,
                     citation="c", source="s", score=0.5, quote="q")],
            run_log=[], stop_reason="final")

    monkeypatch.setattr(cli, "run", fake_run)
    out_file = tmp_path / "report.md"
    rc = cli.main([
        "run", "--prompt", "How does X work?",
        "--cli", "python -m madosho_cli",
        "--provider", "openai", "--model", "gpt-x", "--api-base", "http://h",
        "--budget-chars", "5000", "--max-rounds", "3",
        "--out", str(out_file),
    ])
    assert rc == 0
    assert captured["prompt"] == "How does X work?"
    assert captured["cli_argv"] == ["python", "-m", "madosho_cli"]
    assert captured["provider"] == "openai" and captured["model"] == "gpt-x"
    assert captured["api_base"] == "http://h"
    assert captured["budget"] == (5000, 3)
    # report written to --out and echoed to stdout
    assert out_file.read_text() == "# Hello"
    out = capsys.readouterr()
    assert "# Hello" in out.out
    assert "final" in out.err and "1 citation" in out.err


def test_env_fallback_for_provider_model(capsys, monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "envprov")
    monkeypatch.setenv("RESEARCH_AGENT_MODEL", "envmodel")
    captured = {}

    def fake_run(prompt, *, tools, llm, autonomous_md=None, budget=None):
        captured["provider"] = llm.endpoint.provider
        captured["model"] = llm.endpoint.model
        return Report(markdown="ok", stop_reason="final")

    monkeypatch.setattr(cli, "run", fake_run)
    rc = cli.main(["run", "--prompt", "q"])
    assert rc == 0
    assert captured["provider"] == "envprov" and captured["model"] == "envmodel"
