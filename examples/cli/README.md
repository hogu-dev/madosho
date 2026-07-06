# CLI examples - the two interaction shapes

Two tiny Python CLIs that drive madosho from outside the web UI, one per
interaction shape. Both are stdlib-only (no `pip install`) and just speak HTTP
to the running stack - the same endpoints the Playground uses.

The difference between them is **who calls the LLM - madosho, or you.**

## madosho in the middle (`ask.py`)

You ask; madosho retrieves, builds the prompt, calls the LLM, and returns the
answer plus citations. The CLI never touches an LLM itself.

```
python ask.py --corpus demo "how many engines does the first stage have?"
python ask.py --corpus demo --show-prompt "..."     # also print the assembled prompt
python ask.py --corpus demo --model llama-3.2-1b "..."
```

This is the native `/query` endpoint with an `llm` set - the same path the
Playground takes when you pick a generate model.

## madosho as just the retriever (`retrieve.py`)

madosho returns the ranked chunks and stops. The CLI then makes its **own** path
to an LLM: it builds its own prompt from the chunks and calls the llm-server
directly. Pass `--no-llm` to stop at retrieval (madosho as a pure retriever, or
as an agent's tool).

```
python retrieve.py --corpus demo "how many engines does the first stage have?"
python retrieve.py --corpus demo --no-llm "..."     # pure retrieval, no LLM call
python retrieve.py --corpus demo --top 3 "..."      # how many chunks to feed my prompt
```

This is `/query` with no `llm` field (retrieval only), then a direct
OpenAI-compatible call to the example llm-server.

## Prerequisites

The stack must be up (`docker compose ps` from the repo root), and you need a
corpus with at least one indexed document - a fresh install has none. Create one
in the web UI (or with `madosho_cli`: `create-corpus` + `upload-document`), then
pass its name as `--corpus`. The examples above use a corpus named `demo`.

`ask.py` and the default `retrieve.py` run also need the example llm-server for
generation:

```
cd services/llm-server && docker compose up -d
```

The first call to a model loads it on CPU (~30s); warm after that.

## Authentication

Auth is on by default: requests without a key get 401. Mint a key inside the
running stack and export it - both scripts send it automatically:

```bash
docker compose exec app python -m madosho_server.keys_cli create --name cli-demo --scope read
export MADOSHO_API_KEY=<the key it prints>    # printed once, store it safely
```

`read` scope is enough for `/query`. (Dev opt-out: start the stack with
`MADOSHO_AUTH_ENABLED=0` and skip the key.)

## Endpoints (override with env vars)

| Var                  | Default                     | Used by                        |
|----------------------|-----------------------------|--------------------------------|
| `MADOSHO_QUERY_URL`  | `http://localhost:8001`     | both (retrieval + ask)         |
| `MADOSHO_LLM_URL`    | `http://localhost:8096/v1`  | `retrieve.py` (its own call)   |
| `MADOSHO_API_KEY`    | (none)                      | both, sent as a Bearer token   |

The defaults assume the stack runs on this machine; if it runs elsewhere, set
the URLs to that host (see `docs/HEADLESS.md`, "Reach the stack from another
machine").

Model names for generation depend on what your llm-server serves; the example
`services/llm-server` ships `llama-3.2-1b` (default; US-developed) and
`qwen2.5-1.5b` (labeled alternate -- see `docs/COMPLIANCE.md`).
