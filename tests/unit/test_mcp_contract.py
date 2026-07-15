"""the MCP server's tools are derived straight from the agent-tools manifest -
the single source of truth - so they cannot drift from the CLI / OpenAPI tool server."""
from __future__ import annotations

from madosho_cli.manifest import build_manifest
from madosho_mcp.server import build_tools


def test_mcp_tools_match_manifest_exactly():
    tools = build_tools()
    manifest = {t["name"]: t for t in build_manifest()["tools"]}
    # the same tools, in manifest order
    assert [t.name for t in tools] == [
        "search", "search-doc", "get-doc",
        "list-corpora", "list-documents", "list-pipelines",
        "create-corpus", "upload-document", "build-pipeline",
        "add-document-to-corpus", "document-status",
        "list-goals", "goal-runs", "export-goal-run", "run-goal",
        "list-kbs", "get-kb-page", "search-kb", "add-kb-page", "edit-kb-page",
    ]
    for t in tools:
        # inputSchema IS the manifest parameters (drift fails here)
        assert t.inputSchema == manifest[t.name]["parameters"]
        assert t.description == manifest[t.name]["description"]


def test_build_tools_returns_mcp_tool_objects():
    import mcp.types as types
    tools = build_tools()
    assert len(tools) == 20
    assert all(isinstance(t, types.Tool) for t in tools)
