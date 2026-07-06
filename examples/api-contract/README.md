# madosho HTTP contract

madosho exposes two HTTP planes. Both are FastAPI apps with a live, interactive
schema at `/docs` and a machine-readable spec at `/openapi.json`. This directory
is the "text + example" pair for that contract: this README is the text,
`contract_demo.py` is the runnable script - the foundation every other external
interface (the chat shim, the CLI, MCP) is built on.

## Walk one request through

You have a corpus `demo` with `contract.pdf` indexed (a fresh install has no
corpora - create one in the web UI or with `madosho_cli` first), and the stack
is up. `madosho-host` below is the machine running the stack (`localhost` when
that's this machine). You ask the query plane for the termination clauses two
ways:

- **Retriever:** `POST http://madosho-host:8001/query` with
  `{"corpus": "demo", "prompt": "termination clauses?"}` and NO `llm`. madosho
  retrieves and returns `{"hits": [...]}` - a list of cited chunks. It never calls
  a model. Each hit carries `text`, `score`, `page`, `citation` (e.g.
  `contract.pdf p.4`), a basename'd `source`, the real `document_id`, and the
  `pipeline` it came from.
- **Proxy:** same call WITH `"llm": "<endpoint-name-or-provider:model>"`.
  madosho retrieves, calls the model, and returns
  `{"answer", "citations", "usage", "messages"}` - the answer ends with a `Sources:`
  footer and `messages` is the exact augmented prompt the model saw.

## The two planes

| Plane | App | Port | What it serves |
|-------|-----|------|----------------|
| Control | `madosho_server.api:app` | 8000 | corpora/documents CRUD, ratings, evals, research, proposals, virtual models |
| Query | `madosho_server.query_api:app` | 8001 | native `/query` (retriever + proxy), the OpenAI shim `/v1/*` |

Find the full request/response schema for every endpoint at `/docs` on each port.

## Authentication

Auth is on by default: requests without a Bearer key get 401. Mint a key inside
the running stack and export it - the demo script sends it automatically:

```bash
docker compose exec app python -m madosho_server.keys_cli create --name contract-demo --scope read
export MADOSHO_API_KEY=<the key it prints>    # printed once, store it safely
```

`read` scope covers everything this walk does. (Dev opt-out: start the stack with
`MADOSHO_AUTH_ENABLED=0`.)

## Error conventions (one per plane)

- **Native + control plane:** FastAPI's `{"detail": "<message>"}` envelope.
  Status codes: 404 (not found); 422 (request validation, and a control-plane
  invalid config/recipe `MadoshoError`); 400 (a query-plane `/query`
  `MadoshoError`). Schema: `ErrorResponse` (registered on the query plane;
  control-plane errors use FastAPI's default HTTPException envelope).
- **OpenAI shim (`/v1/*`):** OpenAI-shaped `{"error": {"message", "type", "code"}}`.
  Schema: `OpenAIErrorResponse`. This is deliberate - real OpenAI clients depend on
  it, so the shim is NOT converted to the `{"detail"}` shape.

## The citation `source` label

A chunk's stored `source` is its full filestore path
(`/data/filestore/<hash>/contract.pdf`) - kept for provenance. Every API response
shows the **basename** (`contract.pdf`); `document_id` is the real linkage key.
This basenaming happens once, at the serialization boundary, so every consumer
(the shim Sources footer, the CLI, Scrying, Research) inherits the clean label.

## The OpenAI shim chat endpoint

`POST /v1/chat/completions` is a passthrough: it returns the provider's full
OpenAI `ChatCompletion` object (with a madosho `Sources` footer appended), or an
SSE stream of `chat.completion.chunk` events when `stream: true`. It has no strict
success `response_model` on purpose, so provider fields are never filtered out.

## The runnable walk

`contract_demo.py` is one stdlib-only Python script (no `pip install`) that walks
every surface above and prints the typed, clean responses, so you can watch the
contract work instead of trusting that it does:

1. Both planes' `/health`, and where each one's live schema lives (`/docs`,
   `/openapi.json`).
2. The control plane's typed corpus list (`CorpusRead[]`).
3. Native `/query` as a **retriever** (no `llm`) - typed `hits`, with a clean
   basename'd `source` and `document_id` as the real link.
4. The OpenAI shim `GET /v1/models` (madosho's virtual models).
5. (with `--with-llm`) Native `/query` as a **proxy** (`llm` set) and the
   shim `POST /v1/chat/completions`, non-stream and streaming.
6. The two error envelopes side by side: native `{"detail": ...}` vs the shim's
   OpenAI-shaped `{"error": {...}}`.

```
python contract_demo.py                       # core walk, no LLM provider needed
python contract_demo.py --corpus demo         # pick a corpus
python contract_demo.py --with-llm --model llama-3.2-1b   # also the generate paths
```

The core walk (steps 1-4, 6) needs only the stack up with a corpus indexed - **no
LLM provider**. The generate paths (step 5) are behind `--with-llm` because they
need a provider configured and, for the shim chat, a virtual model registered (add
one in the web Settings). The `--with-llm` paths also need the example llm-server:

```
cd services/llm-server && docker compose up -d
```

## Endpoints (override with env vars)

| Var                   | Default                  | Used for                       |
|-----------------------|--------------------------|--------------------------------|
| `MADOSHO_CONTROL_URL` | `http://localhost:8000`  | health, corpus list            |
| `MADOSHO_QUERY_URL`   | `http://localhost:8001`  | `/query`, the shim, errors     |
| `MADOSHO_API_KEY`     | (none)                   | Bearer key, sent on every call |

See [`examples/cli/`](../cli/) for the two interaction-shape CLIs (`ask.py`,
`retrieve.py`); this demo is the contract-level walk that sits underneath them.
