# tests/unit/test_research_agent_tools.py
"""Tests for the tool layer: the OpenAI-schema mapping, manifest rendering, and
(Task 3) CliToolProvider's argv building + subprocess handling."""
from __future__ import annotations

from research_agent.tools import to_openai_tools, render_manifest
from research_agent.types import ToolSpec


def _specs():
    return [
        ToolSpec(name="search", description="RAG retrieval.",
                 parameters={"type": "object",
                             "properties": {"corpus": {"type": "string"},
                                            "query": {"type": "string"}},
                             "required": ["corpus", "query"]}),
        ToolSpec(name="list-corpora", description="List corpora.",
                 parameters={"type": "object", "properties": {}, "required": []}),
    ]


def test_to_openai_tools_wraps_each_spec():
    out = to_openai_tools(_specs())
    assert out[0] == {
        "type": "function",
        "function": {
            "name": "search",
            "description": "RAG retrieval.",
            "parameters": {"type": "object",
                           "properties": {"corpus": {"type": "string"},
                                          "query": {"type": "string"}},
                           "required": ["corpus", "query"]},
        },
    }
    assert [t["function"]["name"] for t in out] == ["search", "list-corpora"]


def test_render_manifest_lists_names_and_descriptions():
    text = render_manifest(_specs())
    assert "search" in text and "RAG retrieval." in text
    assert "list-corpora" in text
    assert text.startswith("- ")


# ---------------------------------------------------------------------------
# Task 3: CliToolProvider
# ---------------------------------------------------------------------------
import json
import subprocess

import pytest

from research_agent.tools import CliToolProvider
from research_agent.types import ToolResult


class FakeRun:
    """Stands in for subprocess.run: routes argv -> a canned CompletedProcess.

    Keyed by the subcommand (argv[-2], since argv[-1] is always --json for tool
    calls; for `agent-tools` the manifest, argv[-1] is --json and argv[-2] is the
    subcommand too). Records every argv for assertions."""

    def __init__(self, routes):
        self.routes = routes        # subcommand -> (returncode, stdout, stderr)
        self.calls = []             # list[list[str]]

    def __call__(self, argv, capture_output=True, text=True, timeout=None):
        self.calls.append(argv)
        subcommand = argv[1]        # cli_argv is a single prog here, so argv[1] is the subcommand
        rc, out, err = self.routes[subcommand]
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


MANIFEST = {
    "tools": [
        {"name": "search", "description": "RAG retrieval.",
         "parameters": {"type": "object",
                        "properties": {"corpus": {"type": "string"},
                                       "query": {"type": "string"},
                                       "top_k": {"type": "integer"},
                                       "pipeline": {"type": "string"}},
                        "required": ["corpus", "query"]},
         "invocation": {"subcommand": "search",
                        "positional": ["corpus", "query"],
                        "options": ["top_k", "pipeline"]}},
        {"name": "list-corpora", "description": "List corpora.",
         "parameters": {"type": "object", "properties": {}, "required": []},
         "invocation": {"subcommand": "list-corpora", "positional": [], "options": []}},
    ]
}


@pytest.fixture
def fake_run(monkeypatch):
    def install(routes):
        fr = FakeRun(routes)
        monkeypatch.setattr(subprocess, "run", fr)
        return fr
    return install


def test_manifest_parses_into_toolspecs(fake_run):
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), "")})
    provider = CliToolProvider(["madosho-cli"])
    specs = provider.manifest()
    assert [s.name for s in specs] == ["search", "list-corpora"]
    assert specs[0].parameters["required"] == ["corpus", "query"]
    # ran `madosho-cli agent-tools --json`
    assert fr.calls[0] == ["madosho-cli", "agent-tools", "--json"]


def test_invoke_builds_positional_and_option_argv(fake_run):
    hits = {"hits": [{"text": "t", "citation": "c", "document_id": 2}]}
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), ""),
                   "search": (0, json.dumps(hits), "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()  # load the invocation recipes
    result = provider.invoke("search", {"corpus": "aerospace", "query": "sensor failure", "top_k": 3})
    assert isinstance(result, ToolResult) and result.ok
    assert result.data == hits
    # options first (=-joined), then --json, then `--` + positionals in order;
    # pipeline omitted (not given). See invoke()'s injection-hardening comment.
    assert fr.calls[-1] == ["madosho-cli", "search", "--top-k=3", "--json",
                            "--", "aerospace", "sensor failure"]


def test_invoke_flag_like_values_cannot_become_flags(fake_run):
    """Injection hardening: model-supplied values that LOOK like flags must reach
    the CLI as data. Options are =-joined into one argv element; positionals sit
    behind the `--` end-of-options marker."""
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), ""),
                   "search": (0, json.dumps({"hits": []}), "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    result = provider.invoke("search", {"corpus": "--force", "query": "-x",
                                        "pipeline": "--evil"})
    assert result.ok
    assert fr.calls[-1] == ["madosho-cli", "search", "--pipeline=--evil", "--json",
                            "--", "--force", "-x"]


def test_invoke_nonzero_exit_is_structured_error(fake_run):
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), ""),
                   "search": (1, "", "corpus not found: 'nope'")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    result = provider.invoke("search", {"corpus": "nope", "query": "x"})
    assert result.ok is False
    assert "corpus not found" in result.error
    assert result.data is None


def test_invoke_bad_json_is_structured_error(fake_run):
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), ""),
                   "search": (0, "not json", "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    result = provider.invoke("search", {"corpus": "a", "query": "x"})
    assert result.ok is False and "JSON" in result.error


def test_invoke_unknown_tool_is_structured_error(fake_run):
    fake_run({"agent-tools": (0, json.dumps(MANIFEST), "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    result = provider.invoke("does-not-exist", {})
    assert result.ok is False and "unknown tool" in result.error


def test_invoke_before_manifest_auto_loads_the_recipe_table(fake_run):
    """A DIRECT invoke() before manifest() was ever called self-heals: it loads
    the recipe table on first use and runs the tool, instead of returning
    'unknown tool'. This is the path the orchestrator's corpus-size lookup takes
    (before any unit warms the manifest) - its failure left the coverage ledger
    reporting 'size unknown'."""
    hits = {"hits": [{"text": "t", "citation": "c", "document_id": 2}]}
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), ""),
                   "search": (0, json.dumps(hits), "")})
    provider = CliToolProvider(["madosho-cli"])
    # NO provider.manifest() here - invoke must warm it itself
    result = provider.invoke("search", {"corpus": "aerospace", "query": "q"})
    assert result.ok and result.data == hits
    # it shelled `agent-tools` (the warm) before `search`
    assert fr.calls[0] == ["madosho-cli", "agent-tools", "--json"]
    assert fr.calls[-1][:2] == ["madosho-cli", "search"]


def test_invoke_unknown_name_after_load_does_not_reshell(fake_run):
    """Once the table is loaded, a genuinely unknown name fails fast without
    re-running the manifest - the auto-load only fires on an empty table."""
    fr = fake_run({"agent-tools": (0, json.dumps(MANIFEST), "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    calls_before = len(fr.calls)
    result = provider.invoke("does-not-exist", {})
    assert result.ok is False and "unknown tool" in result.error
    assert len(fr.calls) == calls_before   # no extra agent-tools shell


def test_invoke_missing_required_positional_is_structured_error(fake_run):
    """Omitting a required positional arg (corpus) must produce a structured error, not raise."""
    fake_run({"agent-tools": (0, json.dumps(MANIFEST), "")})
    provider = CliToolProvider(["madosho-cli"])
    provider.manifest()
    # "corpus" is the first positional in the search invocation recipe; omit it
    result = provider.invoke("search", {"query": "x"})
    assert result.ok is False
    assert "missing required arg" in result.error or "corpus" in result.error


def test_render_manifest_exact_line_format():
    """render_manifest must produce exactly '- name: description' lines."""
    from research_agent.tools import render_manifest
    specs = [
        ToolSpec(name="name1", description="desc1", parameters={}),
        ToolSpec(name="name2", description="desc2", parameters={}),
    ]
    assert render_manifest(specs) == "- name1: desc1\n- name2: desc2"
