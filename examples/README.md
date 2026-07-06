# madosho examples

Runnable, self-contained examples of talking to a madosho stack over each of its
interfaces. **None of this is required to run madosho** - the stack comes up with
`docker compose up` (see the top-level README's Quickstart). These are here to
show how a client, an agent, or another service wires into it.

Each folder stands on its own with its own README or script. Point the examples
at your stack with the usual env vars (`MADOSHO_CONTROL_URL`, `MADOSHO_QUERY_URL`,
`MADOSHO_API_KEY`); the defaults assume the stack is on `localhost`.

## Start here

- **`demo/`** - the one-command tour. `python examples/demo/demo_all.py` runs
  every external-interface demo in sequence against a running stack. If you only
  open one thing, open this.

## By interface

| Folder | What it shows |
|--------|---------------|
| `api-contract/` | The native HTTP contract: `/query` (cited chunks) and the `/v1/chat/completions` OpenAI shim on the query plane. |
| `cli/` | `madosho-cli` - the two interaction shapes (drive the tools yourself vs. hand off a research question). |
| `mcp/` | Using madosho from an MCP host (Claude Desktop, Cursor, IDE agents) via the `madosho-mcp` server. |
| `chat-frontends/` | Open WebUI wired to madosho two ways: Mode A (the OpenAI shim) and Mode B (the OpenAPI tool server on :8088). |
| `auth/` | Logging in and calling with an API key - the scope gate that guards both planes. |
| `headless/` | Headless write access over HTTP: create corpora, upload documents, build pipelines with no browser. |
| `distributed/` | Running clients on a different machine from the stack, with the proxies forwarding each caller's bearer token. |
| `tls/` | The opt-in Caddy TLS overlay (`compose.tls.yaml`) - local-CA for a LAN, Let's Encrypt for a public host. |

## Related, but not under `examples/`

- **`skills/`** (top level) - the portable agent pack: `SKILL.md` skills you copy
  into your own project so Claude Code, Codex, or opencode can search and research
  a madosho corpus. That folder is self-contained and does not depend on anything
  here.
