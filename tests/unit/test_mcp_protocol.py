"""drive the real MCP protocol in-memory (the SDK's own client<->server harness)
so list_tools / call_tool are exercised end to end, not stubbed. core is monkeypatched."""
from __future__ import annotations

import json

import anyio

from mcp.shared.memory import create_connected_server_and_client_session as connect

from madosho_cli import http
from madosho_mcp import server


def test_protocol_list_and_call(monkeypatch):
    monkeypatch.setattr(server.core, "list_corpora",
                        lambda: {"corpora": [{"id": 1, "name": "verify"}]})

    async def scenario():
        async with connect(server.build_server()) as client:
            listed = await client.list_tools()
            assert [t.name for t in listed.tools] == [
                "search", "search-doc", "get-doc",
                "list-corpora", "list-documents", "list-pipelines",
                "create-corpus", "upload-document", "build-pipeline",
                "add-document-to-corpus", "document-status",
                "list-goals", "goal-runs", "export-goal-run", "run-goal",
            ]
            result = await client.call_tool("list-corpora", {})
            assert result.isError is False
            # the SDK puts a returned dict in structuredContent AND a JSON TextContent
            assert result.structuredContent == {"corpora": [{"id": 1, "name": "verify"}]}
            assert json.loads(result.content[0].text) == {
                "corpora": [{"id": 1, "name": "verify"}]}

    anyio.run(scenario)


def test_protocol_cli_error_is_iserror(monkeypatch):
    def boom():
        raise http.CliError("could not reach the stack; is it up?")

    monkeypatch.setattr(server.core, "list_corpora", boom)

    async def scenario():
        async with connect(server.build_server()) as client:
            result = await client.call_tool("list-corpora", {})
            assert result.isError is True
            assert "could not reach the stack" in result.content[0].text

    anyio.run(scenario)
