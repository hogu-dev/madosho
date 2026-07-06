# Chat frontends

madosho works with chat apps like Open WebUI two ways. Both are real: one turns
madosho into an OpenAI-compatible server that the chat app talks to directly (Mode
A, proxy); the other turns madosho into a retrieval tool the chat app's model can
call during a conversation (Mode B, context source).

- **Mode A (proxy):** Open WebUI connects to madosho's OpenAI shim on port 8001.
  The user picks a madosho virtual model from the dropdown. A chat message goes to
  madosho, madosho retrieves context and calls a configured LLM provider, then
  streams the answer back as an OpenAI response. Open WebUI sees a normal OpenAI
  server; it does not know about the retrieval happening underneath.

- **Mode B (context source):** Open WebUI connects to madosho's OpenAPI tool server
  on port 8088. Open WebUI fetches the tool server's schema and registers the tools
  (search, search-doc, get-doc, list-corpora, list-documents, list-pipelines).
  During a chat backed by any model the user has in Open WebUI, that model can call
  `search` to pull ranked chunks out of madosho, then answer over them. madosho does
  retrieval only; it does not touch the LLM.

## Authentication

Auth is on by default, and it applies to both modes: the shim (query plane) and the
tool server both want `Authorization: Bearer <key>`. Mint a key first:

```bash
docker compose exec app python -m madosho_server.keys_cli create --name chat-frontend --scope read
```

- **Mode A:** put this key in Open WebUI's connection "API key" field - it is sent
  as the Bearer token to the shim.
- **Mode B:** set the key as the tool server's auth/Bearer token when you register
  it (the tool server forwards each caller's token to the backend, so the caller's
  own scope applies).
- The demo script reads `MADOSHO_API_KEY` from the environment.

(Dev opt-out: start the stack with `MADOSHO_AUTH_ENABLED=0`; then any string works
as the key.)

## Standing up Open WebUI

> The UI paths below were verified against **Open WebUI 0.9.2** (June 2026). Open
> WebUI ships from a rolling `:main` image and moves its menus often - if a label has
> moved, the Settings search box (type "tools" or "connection") is the fastest way to
> find it again.

The repo includes an opt-in Open WebUI service under the `frontend` compose
profile. Starting the full stack with the profile pre-wires the shim connection:

```
docker compose --profile frontend up
```

To run Open WebUI separately (for example, if you already have it running
elsewhere), use the standalone docker run command. The key env vars pre-configure
both connections:

```
docker run -d -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8001/v1 \
  -e OPENAI_API_KEY=<your madosho key> \
  -e WEBUI_AUTH=false \
  ghcr.io/open-webui/open-webui:main
```

Open WebUI is then at http://localhost:3000.

## Networking note

Open WebUI resolves connection URLs from its own container (its backend), not from
your browser. The right hostname depends on how you started it:

| Open WebUI start method          | madosho shim URL                          | madosho tool server URL                    |
|----------------------------------|-------------------------------------------|--------------------------------------------|
| `--profile frontend` (compose)   | `http://query:8001/v1`                    | `http://toolserver:8088`                   |
| `docker run` (separate)          | `http://host.docker.internal:8001/v1`     | `http://host.docker.internal:8088`         |
| bare host (not in docker)        | `http://localhost:8001/v1`                | `http://localhost:8088`                    |

Using `localhost` from inside a container reaches the container itself, not the
host. Use the service name (compose network) or `host.docker.internal` (separate
container on the same host).

If the madosho stack runs on a different machine altogether, the table collapses:
use that machine's hostname or IP in both columns (e.g.
`http://madosho-host:8001/v1`) regardless of how Open WebUI was started - the
container-networking rules above only matter when Open WebUI and the stack share
one host.

**Exception - user-level tool servers (0.9.x "Manage Tool Servers") are fetched by
your BROWSER, not the backend.** So for that path use `http://localhost:8088`
regardless of how Open WebUI was started. The table above applies to backend-side
connections: the shim (Mode A), and admin/global tool servers added in the Admin
Panel. Match the URL to who makes the request, not to where Open WebUI runs.

## Mode A walkthrough: Open WebUI as a proxy client

1. Open http://localhost:3000 and sign in (or skip if `WEBUI_AUTH=false`).

2. Open the Admin Panel (click your name/avatar at the bottom-left -> Admin Panel),
   then Settings > Connections. (Older builds reached this via a wrench icon; 0.9.x
   moved connection management into the Admin Panel.)

3. Under OpenAI API, add a connection:
   - Base URL: `http://query:8001/v1` (compose profile) or
     `http://host.docker.internal:8001/v1` (separate container)
   - API key: your madosho key (see Authentication above)

4. Save. Open WebUI fetches `/v1/models` and populates the model dropdown with
   madosho's virtual models (the ones you registered in madosho's Settings page).

5. Pick a madosho virtual model from the dropdown, type a message, and send.
   madosho retrieves context from the corpus bound to that model, calls the
   configured LLM provider, and streams the answer. The answer includes a
   "Sources:" footer with the cited chunks.

For this to generate an answer, you need:
- A corpus indexed in madosho.
- At least one virtual model registered in madosho's Settings page, pointing at
  a live LLM provider (configured under Settings > LLM Providers).

## Mode B walkthrough: Open WebUI as a tool-calling client

1. In Open WebUI, open Settings -> Tools. In 0.9.x this is the **"Manage Tool
   Servers"** panel (the old wrench-icon "Admin Settings > Tools" is gone; use the
   Settings search for "tools" if you do not see it).

2. Add a new tool server. The URL depends on WHO fetches the schema:
   - User-level "Manage Tool Servers" fetches from your **browser**, so use
     `http://localhost:8088` (your machine reaches the host-published port).
   - The Admin Panel's global tool servers fetch from the **backend**, so there use
     `http://toolserver:8088` (compose service name) or `http://host.docker.internal:8088`.

   The "Add" modal pre-fills `https://`; change it to plain `http://` or it silently
   fails to connect. Set the connection's auth/Bearer token to your madosho key.

3. Save. Open WebUI fetches `/openapi.json` from the tool server and displays the
   six tools: search, search-doc, get-doc, list-corpora, list-documents,
   list-pipelines. (The tool server sends permissive CORS headers, so the
   browser-side fetch is not blocked.)

4. Start a new chat with any model that supports tool calls (your own model in
   Open WebUI, not a madosho virtual model). Enable Tools for the chat (the tools
   toggle in the chat bar).

5. Ask a question about a document in madosho. The model calls `search` with a
   corpus name and a query. madosho returns ranked chunks. The model reads them and
   answers. madosho does no generation; it is a retrieval tool only.

For this to work:
- A corpus must be indexed in madosho.
- The model you use in Open WebUI must support function/tool calling.
- madosho does not need an LLM provider configured for Mode B.

## Troubleshooting

**The model never calls the search tool.**
Open WebUI has a known issue where it silently sends `tool_servers=[]` to the
model even when a tool server is registered (open-webui/open-webui#21805). To
work around it:
- Re-save the tool server entry in Admin Settings > Tools.
- In the chat, confirm the Tools toggle is on (the hammer icon in the message bar).
- Check that Open WebUI actually fetched the schema: the tool server entry should
  show the tool count after saving.

**401 / "unauthorized" from either connection.**
Auth is on by default. Give the connection a valid madosho key (see Authentication
above), or start the stack with `MADOSHO_AUTH_ENABLED=0` for an open dev box.

**"operationId" errors / tools not recognized.**
Each endpoint on the tool server must have an `operationId` for Open WebUI to
register it as a callable tool. madosho sets the operationId for each endpoint to
the tool name (search, search-doc, get-doc, list-corpora, list-documents,
list-pipelines). If you are building a custom tool server, this is required.

**"Failed to connect" when adding the tool server.**
Two common causes in 0.9.x:
- Wrong host for who fetches. User-level "Manage Tool Servers" fetches from your
  browser -> use `http://localhost:8088`. The Admin Panel's global tool servers fetch
  from the backend container -> use `http://toolserver:8088` or
  `http://host.docker.internal:8088` (there, `localhost` means the container itself).
- `https://` left in the URL -> change it to plain `http://`.

The tool server sends `Access-Control-Allow-Origin: *`, so a correctly-targeted
browser fetch is not blocked by CORS.

**Mode A: no models in the dropdown.**
No virtual models are registered yet. Go to madosho's Settings page and add at
least one virtual model.

**Mode A: answer is empty or returns an error.**
The virtual model's configured provider may not be reachable. Check madosho's
LLM provider settings and confirm the provider endpoint is up.

## Known behavior

**Two system messages.** When a client sends a request with its own system
message, the shim prepends a retrieval-context system message in front of it.
The conversation seen by the provider has two system messages. Most providers
tolerate this.

**Mid-stream provider errors.** If the LLM provider returns an error after
streaming has begun, the SSE stream breaks mid-response rather than returning
a clean error envelope. This is a known limitation.

## Contract reference

### Mode A: shim endpoints (port 8001)

| Method | Path                      | What it does                                              |
|--------|---------------------------|-----------------------------------------------------------|
| GET    | `/v1/models`              | Lists madosho's virtual models in OpenAI format           |
| POST   | `/v1/chat/completions`    | Retrieves context, proxies to provider, returns answer    |
| GET    | `/health`                 | Health check                                              |
| GET    | `/openapi.json`           | OpenAPI schema for the shim                               |

The `POST /v1/chat/completions` endpoint accepts `stream: true` for SSE streaming
and `stream: false` (default) for a single JSON response. The response shape
matches the OpenAI ChatCompletion format. Errors use the OpenAI error envelope:
`{"error": {"message": "...", "type": "...", "code": ...}}`.

### Mode B: tool-server endpoints (port 8088)

| Method | Path                | operationId      | What it does                                      |
|--------|---------------------|------------------|---------------------------------------------------|
| POST   | `/search`           | search           | Retrieve ranked chunks from a corpus              |
| POST   | `/search-doc`       | search-doc       | Retrieve ranked chunks from one document (by id)  |
| POST   | `/get-doc`          | get-doc          | Fetch full text for a document (no retrieval)     |
| POST   | `/list-corpora`     | list-corpora     | List available corpora                            |
| POST   | `/list-documents`   | list-documents   | List documents in a corpus                        |
| POST   | `/list-pipelines`   | list-pipelines   | List pipelines on a document or across a corpus   |
| GET    | `/openapi.json`     | (schema)         | Full OpenAPI spec; Open WebUI fetches this        |
| GET    | `/health`           | (health)         | Health check                                      |

Each POST endpoint's request body matches the parameters defined in the
agent-tools manifest (`madosho_cli/manifest.py`). The manifest is the single
source of truth; the tool server schema is generated from it, so the two cannot
drift.

**`/search` body fields:**

| Field      | Type    | Default | Description                                      |
|------------|---------|---------|--------------------------------------------------|
| `corpus`   | string  | (req)   | Corpus name to search                            |
| `query`    | string  | (req)   | The retrieval query                              |
| `top_k`    | int     | 5       | Number of chunks to return                       |
| `pipeline` | string  | null    | Pipeline name override (null = effective default)|

**`/search` response:** `{"hits": [...]}` where each hit has `text`, `citation`,
`score`, `document_id`, `pipeline`, `page`, and `source` fields.

**`/search-doc` body fields:** `document_id` (int, required), `query` (string,
required), `top_k` (int, default 8), `pipeline` (string, optional). Same `{"hits":
[...]}` response as `/search`, scoped to one document.

**`/get-doc` body fields:** `document_id` (int, required), `pipeline` (string,
optional). Returns the full document text (no retrieval).

**`/list-pipelines` body fields:** `corpus` (string, optional) or `document_id`
(int, optional) - give exactly one. Returns `{"pipelines": [...]}` with each
pipeline's name, rating, status, and whether it is effective.

**`/list-documents` body fields:** `corpus` (string, required).

## Example script

`chat_frontends_demo.py` in this directory is a stdlib-only smoke test that
exercises both doors against the running stack. It runs the no-LLM parts
unconditionally (Mode B `/openapi.json` + `/search`, Mode A `/v1/models`) and
gates the proxy chat behind `--with-llm`.

```
# from the repo root, stack up first; export MADOSHO_API_KEY (see Authentication)
python examples/chat-frontends/chat_frontends_demo.py --corpus demo
python examples/chat-frontends/chat_frontends_demo.py --with-llm --model <virtual-model>
```

Override the default endpoints with environment variables:
- `MADOSHO_QUERY_URL` (default `http://localhost:8001`)
- `MADOSHO_TOOLSERVER_URL` (default `http://localhost:8088`)

See `examples/api-contract/` for the lower-level HTTP contract walk, and
`examples/cli/` for the two interaction-shape CLIs (`ask.py`, `retrieve.py`).
