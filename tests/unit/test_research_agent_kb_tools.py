import subprocess
from research_agent.tools import LlmkbToolProvider, MultiToolProvider
from research_agent.types import ToolSpec, ToolResult


def test_llmkb_provider_manifest_lists_kb_tools():
    names = [s.name for s in LlmkbToolProvider("/tmp/kb").manifest()]
    assert names == ["kb_add_page", "kb_get_page"]


def test_llmkb_provider_add_page_argv_and_stdin(monkeypatch):
    calls = []

    def fake_run(argv, capture_output, text, timeout, input=None):
        calls.append((argv, input))
        return subprocess.CompletedProcess(argv, 0, stdout='{"path": "wiki/concepts/x.md"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = LlmkbToolProvider("/tmp/kb").invoke(
        "kb_add_page",
        {"type": "concept", "title": "X", "description": "d",
         "tags": ["a", "b"], "sources": ["raw/1.pdf"], "body": "hi"})
    assert res.ok and res.data["path"].endswith("x.md")
    argv, stdin = calls[-1]
    assert argv[0] == "llmkb" and "add-page" in argv
    assert "--kb" in argv and "/tmp/kb" in argv
    assert "--tags" in argv and "a,b" in argv
    assert argv.count("--source") == 1 and "raw/1.pdf" in argv
    assert "--body-file" in argv and "-" in argv and "--json" in argv
    assert stdin == "hi"


def test_llmkb_provider_reports_cli_failure(monkeypatch):
    def fake_run(argv, capture_output, text, timeout, input=None):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="error: page already exists")

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = LlmkbToolProvider("/tmp/kb").invoke("kb_get_page", {"title": "X"})
    assert not res.ok and "already exists" in res.error


def test_multi_provider_routes_by_name():
    class P:
        def __init__(self, names):
            self.names, self.seen = names, []

        def manifest(self):
            return [ToolSpec(n, n, {}) for n in self.names]

        def invoke(self, name, args):
            self.seen.append(name)
            return ToolResult(ok=True, data=name)

    a, b = P(["search"]), P(["kb_add_page", "kb_get_page"])
    m = MultiToolProvider([a, b])
    assert [s.name for s in m.manifest()] == ["search", "kb_add_page", "kb_get_page"]
    assert m.invoke("kb_add_page", {}).data == "kb_add_page"
    assert b.seen == ["kb_add_page"] and a.seen == []
    assert not m.invoke("nope", {}).ok
