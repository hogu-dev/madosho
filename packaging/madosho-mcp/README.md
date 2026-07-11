# madosho-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes a
[madosho](https://github.com/hogu-dev/madosho) RAG corpus as retrieval tools, so an
MCP host (Claude Desktop, IDEs, agents) can search your documents. It re-publishes
the madosho agent-tools manifest as MCP tool definitions and delegates every call to
the shared `madosho-cli` orchestration core, so the CLI, the OpenAPI tool server, and
this MCP server share one behavior and cannot drift.

Pure HTTP client — imports nothing from the madosho kernel or server.

```
pip install madosho-mcp
madosho-mcp            # stdio transport (an MCP host spawns this)
madosho-mcp --http     # streamable-HTTP transport
```

Apache-2.0.
