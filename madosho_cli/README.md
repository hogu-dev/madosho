# madosho-cli

A thin command-line client over madosho's HTTP API. Double duty: humans run it to
inspect and drive a running madosho; a research agent drives it too (every
subcommand takes `--json`). It speaks only HTTP - no kernel or DB imports - so it
is a pure client. Stdlib only (no `pip install` beyond madosho itself).

## Commands

Read side:

```
madosho-cli search <corpus> <query> [--top-k N] [--pipeline NAME] [--json]
madosho-cli search-doc <document_id> <query> [--top-k N] [--pipeline NAME] [--json]
madosho-cli get-doc <document_id> [--pipeline NAME] [--json]
madosho-cli list-corpora [--json]
madosho-cli list-documents <corpus> [--json]
madosho-cli list-pipelines (--corpus NAME | --document-id ID) [--json]
madosho-cli document-status <document_id> [--json]
madosho-cli list-runs <corpus_id> [--type research|eval] [--active] [--json]
madosho-cli agent-tools [--json]
```

Write side:

```
madosho-cli create-corpus <name> [--json]
madosho-cli upload-document <path> [--filename F] [--corpus NAME]
            [--parser P] [--chunker C] [--embedder E] [--options JSON]
            [--no-wait] [--json]
madosho-cli build-pipeline <document_id> <name> [--parser P] [--chunker C]
            [--embedder E] [--options JSON] [--config JSON] [--no-wait] [--json]
madosho-cli add-document-to-corpus <corpus> <document_id> [--json]
madosho-cli cancel-run <run_id> [--type research|eval] [--yes] [--json]
```

- `search` - RAG retrieval over a corpus (`POST /query` with no `llm`). Returns
  ranked, cited chunks. `--pipeline` retrieves through a named pipeline (overrides
  each document's effective pipeline); `--top-k` truncates the result client-side
  (default 8). Retrieval *mode* (keyword/semantic/hybrid) is baked into a
  pipeline's operator stack, so pick a stack with `--pipeline`, not a flag.
- `search-doc` - the same RAG retrieval scoped to a single document by id (works
  even for a loose document in no corpus). Same `{hits}` shape and options as
  `search`.
- `get-doc` - the full extracted text of one document (NOT retrieval), assembled
  from its effective pipeline's chunks in order. `--pipeline` reads a named pipeline
  instead.
- `list-corpora` / `list-documents` - discovery / target resolution.
- `list-pipelines` - the named pipelines built on a document (`--document-id`) or
  across a corpus (`--corpus`), with ratings, so you can discover names to pass via
  `--pipeline`. Exactly one scope.
- `document-status` - the current status of a document (uploaded / indexing / indexed).
- `list-runs` / `cancel-run` - inspect and cancel research or eval runs on a corpus.
- `agent-tools` - emits the **tool manifest** a research agent consumes (see below).
- `create-corpus` / `upload-document` / `build-pipeline` / `add-document-to-corpus` -
  the headless write path: stand up a corpus and index documents with no web UI.
  `upload-document` blocks until the document is indexed (pass `--no-wait` to
  return immediately and poll with `document-status`).

`<corpus>` is always a corpus **name**; `<document_id>` is a numeric **id** (from
`list-documents`).

## Endpoints and auth (override with env vars)

| Var | Default | Used by |
|-----|---------|---------|
| `MADOSHO_QUERY_URL` | `http://localhost:8001` | `search`, `search-doc`, `list-pipelines --corpus` (query plane) |
| `MADOSHO_CONTROL_URL` | `http://localhost:8000` | everything else (control plane) |
| `MADOSHO_API_KEY` | (none) | sent as `Authorization: Bearer` on every call |

The defaults assume the stack runs on the same machine as the CLI. It does not
have to: point the URLs at whatever host runs the stack (see `docs/HEADLESS.md`,
"Reach the stack from another machine").

Auth is on by default: mint a key inside the running stack and export it.
`read` scope covers the read side; the write side needs `write`:

```bash
docker compose exec app python -m madosho_server.keys_cli create --name cli --scope write
export MADOSHO_API_KEY=<the key it prints>    # printed once, store it safely
```

The stack must be up (`docker compose ps` from the repo root).

## JSON contract

Under `--json`:
- **stdout** carries the result JSON object or nothing (if an error occurs).
- **All errors** print to stderr and exit with non-zero status (what a tool driver
  keys off). Never print error JSON to stdout.
- **Top-level keys** per command: `{corpora}` (list-corpora), `{corpus,documents}`
  (list-documents), `{hits}` (search, search-doc), document text keys (get-doc),
  `{pipelines, ...}` (list-pipelines), or `{tools}` (agent-tools).

## The agent-tools contract (reuse without MCP)

`madosho-cli agent-tools --json` emits `{"tools": [ ... ]}`. Each tool:

- `name` - the subcommand.
- `description` - what it does (fed to the model).
- `parameters` - a JSON Schema (`type: object`, `properties`, `required`),
  directly usable as an OpenAI function-tool schema.
- `invocation` - `{subcommand, positional, options}`. A tool provider builds the
  argv as `madosho-cli <subcommand> <positional values...> [--<opt> <value> ...]
  --json`, where option param names convert underscores to hyphens
  (`top_k` -> `--top-k`). Required params are always positional.

Any application that ships a CLI emitting a compatible `agent-tools` manifest and
accepting `--json` subcommands can be driven by the same research agent. That is
the reuse contract, in place of MCP.

## alchemy (autonomous goals)

Standing, named goals that run autonomously over a corpus and produce
versioned, exportable drafts. CLI-only in this release (not on MCP/toolserver).

```
madosho-cli alchemy create <name> --corpus NAME --goal TEXT [--coverage search] [--json]
madosho-cli alchemy run <ref> --provider P --model M [--coverage search]
            [--guidance TEXT] [--based-on VERSION] [--max-llm-calls N]
            [--no-wait] [--json]
madosho-cli alchemy status <ref> [--run VERSION] [--json]
madosho-cli alchemy export <ref> [--run VERSION] [-o FILE]
madosho-cli alchemy finalize <ref> --run VERSION [--json]
madosho-cli alchemy list [--json]
madosho-cli alchemy runs <ref> [--json]
madosho-cli alchemy cancel <run_id> [--json]
```

- `<ref>` is a goal's name or numeric id (`--corpus` on `create` is always a
  **name**, resolved the same way as `list-documents`/`upload-document`).
- `run` blocks until the run reaches a terminal status (`done`/`failed`/
  `cancelled`), printing progress lines, and exits non-zero on `failed` -
  pass `--no-wait` to return immediately with the pending run and poll
  yourself with `status`. `--based-on` picks which prior version to revise;
  default is the goal's latest version that has a draft.
- `export`/`status` default `--run` to the goal's latest run if omitted.
- `finalize` marks one version as the goal's canonical output (clears any
  prior final version on that goal).

Worked example:

```
madosho-cli alchemy create find_vuln --corpus secdocs --goal "map every vulnerability discussed"
madosho-cli alchemy run find_vuln --provider openai --model gpt-4o-mini
madosho-cli alchemy export find_vuln            # -> find_vuln-v1.md
madosho-cli alchemy run find_vuln --provider openai --model gpt-4o-mini \
    --guidance "dig into the 2024 incidents"    # -> v2, revises v1
madosho-cli alchemy finalize find_vuln --run 2
```
