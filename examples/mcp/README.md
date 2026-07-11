# madosho MCP server - use madosho from an MCP host

madosho exposes its retrieval tools over the Model Context Protocol (MCP), so any
MCP-native host (Claude Desktop, Claude Code, Cursor, IDE agents) can call them during
a conversation. madosho does retrieval only here - the host's own model forms the
answer; madosho never touches a language model.

Same tools as `madosho-cli` and the OpenAPI tool server - all three derive from one
`agent-tools` manifest, so they cannot drift.

## A concrete run, start to finish

You have a corpus `contracts` with a few PDFs indexed (create one in the web UI or
with `madosho_cli` first - a fresh install has no corpora), and madosho is up
(query on 8001, control on 8000). In the snippets below, `madosho-host` is the
machine running the stack: use `localhost` when the Docker stack runs on this
same machine, its hostname or IP when it runs elsewhere (a home server, a cloud
VM).

**1. Install the server.**

From a clone of this repo:

```
pip install madosho-mcp
```

That pulls the `mcp` SDK (MIT) as a dependency and puts the `madosho-mcp` entry point
on your PATH. (PyPI packages are planned; until they land, install from the clone.)

**2. Mint an API key.**

Auth is on by default; the MCP server sends `MADOSHO_API_KEY` as a Bearer token on
every call. Read scope is enough for the retrieval tools:

```
docker compose exec app python -m madosho_server.keys_cli create --name mcp-host --scope read
```

The key is printed once - store it safely.

**3. Add madosho to your MCP host config.**

For Claude Desktop, open `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or the equivalent on your platform, and add:

```json
{
  "mcpServers": {
    "madosho": {
      "command": "madosho-mcp",
      "env": {
        "MADOSHO_QUERY_URL": "http://madosho-host:8001",
        "MADOSHO_CONTROL_URL": "http://madosho-host:8000",
        "MADOSHO_API_KEY": "PASTE-YOUR-KEY-HERE"
      }
    }
  }
}
```

The host spawns `madosho-mcp` as a subprocess and speaks JSON-RPC over stdio.
`claude_desktop_config.example.json` in this directory has the snippet ready to copy.

**4. Start a session in the host.**

The host calls `tools/list`. `madosho-mcp` returns the tools it got from the
`agent-tools` manifest (`madosho_mcp/server.py` calls `manifest.build_manifest()`
at startup, so the schema is always current).

The host sees:
- `search` - retrieve ranked chunks from a corpus
- `search-doc` - retrieve ranked chunks from a single document (by id)
- `get-doc` - fetch the full text of a document (no retrieval)
- `list-corpora` - list available corpora
- `list-documents` - list documents in a corpus
- `list-pipelines` - list pipelines on a document or across a corpus

**5. The host calls search.**

The user asks "what are the termination clauses in the contracts corpus?". The host's
model decides to call `search` with `{"corpus": "contracts", "query": "termination
clauses"}`. `madosho-mcp` forwards the call to the query plane at `MADOSHO_QUERY_URL`,
gets back ranked chunks (text, score, page, citation, pipeline), and returns them as
structured content. The model reads the chunks and writes its answer.

## Reference

### URL (HTTP) transport

Some hosts connect to MCP servers by URL rather than by spawning a process. Start the
HTTP transport with:

```
madosho-mcp --http
madosho-mcp --http --host 0.0.0.0 --port 8089
```

This serves streamable-HTTP at `/mcp` (default port 8089). Register
`http://localhost:8089/mcp` in your host's MCP server list. In HTTP mode the server
forwards each caller's own `Authorization` header upstream instead of using its env
key, so every client authenticates as itself.

### Environment variables

| Variable              | Default                   | What it points at                        |
|-----------------------|---------------------------|------------------------------------------|
| MADOSHO_QUERY_URL     | http://localhost:8001     | query plane (search, search-doc)         |
| MADOSHO_CONTROL_URL   | http://localhost:8000     | control plane (get-doc, list-corpora/docs/pipelines) |
| MADOSHO_API_KEY       | (none)                    | Bearer key sent on every call (stdio mode) |

### No-drift guarantee

The tool names, descriptions, and input schemas come from one place:
`madosho_cli/manifest.py` (`build_manifest()`). The CLI (`madosho-cli`), the OpenAPI
tool server (`madosho-toolserver`), and this MCP server all call the same function. If
a tool's schema changes in the manifest, all three interfaces update on the next start.
There is no separate MCP schema to maintain.

The contract guard in `tests/unit/test_mcp_contract.py` enforces this: it compares
the MCP server's tool list against the manifest at test time and fails if they diverge.

### Smoke test

`mcp_demo.py` in this directory launches `python -m madosho_mcp` as a real stdio
server, calls `list-corpora`, and optionally calls `search`. Needs a running stack
(and `MADOSHO_API_KEY` exported). No LLM required.

```
python mcp_demo.py
python mcp_demo.py --corpus contracts --query "termination clauses"
```

Unlike the other example packs this one requires the `mcp` client SDK (it speaks the
MCP protocol to the server); the `madosho-mcp` package installed above covers it.
