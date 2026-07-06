# madosho external-interface demo trail

Run this to see each external interface work. This directory aggregates the four
per-interface example packs (HTTP contract, chat frontends, MCP server, CLI +
agent skills) into one ordered trail. Each pack remains the runnable source of
truth; `demo_all.py` stitches them together and this README links their per-pack
docs.

## Prerequisites

1. **Stack up:**

   ```
   docker compose up
   ```

   Control plane on :8000, query plane on :8001, tool server on :8088.

2. **An API key.** Auth is on by default. Mint a key (the web UI's Settings > API
   Keys page, or the CLI below), then export it before running any demo:

   ```
   docker compose exec app python -m madosho_server.keys_cli create --name demo --scope write
   export MADOSHO_API_KEY=<the key it prints>
   ```

   `demo_all.py` and the CLI/MCP-stdio demos inherit the key from the shell
   automatically; the direct-HTTP demos read it from env and attach it as a
   Bearer header. `read` scope covers everything except the agent pack's research
   run, which writes. (If your stack runs with `MADOSHO_AUTH_ENABLED=0`, the key
   is optional.)

3. **A corpus indexed.** A fresh install has no corpora - create one (web UI or
   `madosho_cli`) and index at least one document. The pack demos default to a
   corpus named `demo`; pass `--corpus <name>` to point them at yours.

4. **Optional - an LLM provider** (only for the `--with-llm` generate paths).
   Any OpenAI-compatible endpoint works; `services/llm-server` is a ready-made
   local example.

## Auth verification trail

These four stdlib-only scripts verify auth and headless write behavior. Run them
in order before the full interface demos; each one is a fast PASS/FAIL check
against the live stack.

**Auth lock probe** (`examples/auth/probe.py`): confirms /health is open,
no-key -> 401, a read key reads, a write key writes directly against the control
plane. No corpus needed.

```
MADOSHO_API_KEY=mdsh_... python examples/auth/probe.py http://madosho-host:8000
```

(`madosho-host` = the machine running the stack; `localhost` when it's the
Docker stack on this same machine.)

**Browser cookie flow** (`examples/auth/login.py`): posts the key to
/auth/login, captures the httpOnly session cookie, then makes an authenticated GET
carrying only the cookie. Proves the web UI login path.

```
MADOSHO_API_KEY=mdsh_... python examples/auth/login.py http://madosho-host:8000
```

**Headless document ingest** (`examples/headless/ingest.py`): create corpus,
base64-ingest a tiny document, poll until indexed, search. Full write path via HTTP.

```
MADOSHO_API_KEY=mdsh_... python examples/headless/ingest.py
```

**Toolserver pass-through** (`examples/distributed/proof.py`): routes a read
and a write through the toolserver (:8088). A read key gets 200 on the read and 403
on the write, proving the proxy forwarded the caller's actual key rather than
injecting an ambient write key. A write key gets 200 and 201 (also proves forwarding).

```
MADOSHO_API_KEY=mdsh_... python examples/distributed/proof.py
```

See `docs/AUTH.md` for the pass-through model and `docs/HEADLESS.md` for
reach-from-another-machine setup.

## One-command proof

```
python examples/demo/demo_all.py
```

Runs all four headless demos in sequence and prints a PASS/FAIL line per
interface:

```
[PASS] api-contract
[PASS] chat-frontends
[PASS] mcp
[FAIL] agent-skills
  madosho-cli: command not found
```

Exits 0 only if every interface passes; exits 1 if any fail (`echo $?` tells you).
A `[FAIL]` line prints the last few lines of that demo's output to help diagnose.

With generate paths (needs a provider up):

```
python examples/demo/demo_all.py --with-llm --corpus <name> --model <m> --provider <p>
```

`--corpus <name>` overrides every demo's default for a uniform run. `--model` is the
raw provider model (e.g. `gemma-4-e4b`) used by the api-contract proxy and the
agent-skills research run; the chat-frontends proxy chat self-resolves the first
registered virtual model, so a single `--model` drives all four generate paths.
`--provider` is forwarded to the demos that accept it.

## Per-interface commands

### api-contract - native /query + OpenAI shim

```
python examples/api-contract/contract_demo.py
```

Default corpus: `demo`. Headless walk: both planes' /health, typed corpus
list, native /query as a retriever (no LLM), /v1/models, two error
envelopes (native `{"detail": ...}` vs shim `{"error": {...}}`).

Add the generate paths:

```
python examples/api-contract/contract_demo.py --with-llm --model llama-3.2-1b
```

`--with-llm` runs native /query as a proxy and shim /v1/chat/completions
non-stream + streaming.

Env overrides: `MADOSHO_CONTROL_URL` (default `http://localhost:8000`),
`MADOSHO_QUERY_URL` (default `http://localhost:8001`).

Full reference: `examples/api-contract/README.md`

### chat-frontends - Mode A proxy + Mode B tool server

```
python examples/chat-frontends/chat_frontends_demo.py
```

Default corpus: `demo`. Headless: Mode B reads /openapi.json from the tool
server and runs a /search; /v1/models lists the registered virtual models.

Add the Mode A proxy chat:

```
python examples/chat-frontends/chat_frontends_demo.py --with-llm --model <virtual-model>
```

`--model` is the virtual model name (leave it out to use the first registered
model). Needs a provider up and a virtual model registered in Settings.

Env overrides: `MADOSHO_QUERY_URL` (default `http://localhost:8001`),
`MADOSHO_TOOLSERVER_URL` (default `http://localhost:8088`).

Full reference: `examples/chat-frontends/README.md`

### mcp - MCP server (stdio)

First install the MCP client SDK (once):

```
pip install "mcp>=1.8,<2"
```

Then:

```
python examples/mcp/mcp_demo.py
```

Launches `madosho-mcp` as a stdio child, lists its tools, and calls list-corpora.
No LLM needed, and no corpus needed until you add a search:

```
python examples/mcp/mcp_demo.py --corpus <name> --query "overview"
```

`--query` defaults to `overview`.

Full reference: `examples/mcp/README.md`

### agent-skills - CLI + portable skills

```
python skills/agent_pack_demo.py
```

Headless: parses both SKILL.md files, then probes `madosho-cli agent-tools` and
`madosho-cli list-corpora`. No LLM or corpus needed for this path.

Add a server-side research run:

```
python skills/agent_pack_demo.py --with-llm --corpus <name> \
    --provider <p> --model <m>
```

All three of `--corpus`, `--provider`, and `--model` are required with
`--with-llm`. Install the skills into a project first:

```
python skills/install.py --target <your-project-dir>
```

Full reference: `skills/README.md`

## Interactive doors (manual walk - not scriptable)

These two paths involve a live chat UI or a native MCP host config and cannot be
driven by a single command.

### Open WebUI (proxy chat + tool registration)

1. Start the frontend profile:

   ```
   docker compose --profile frontend up
   ```

2. Follow the walkthrough in `examples/chat-frontends/README.md`.

### Real MCP host (Claude Desktop, Cursor, or similar)

Wire `madosho-mcp` per `examples/mcp/README.md` using the config shape in
`examples/mcp/claude_desktop_config.example.json`. The host spawns `madosho-mcp`
over stdio and exposes the six retrieval tools (search, search-doc, get-doc,
list-corpora, list-documents, list-pipelines) to the model.
