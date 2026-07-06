# Example: local CPU llm-server for madosho

This is an **example and sanity check**, not a required part of madosho.

madosho's answer lane talks to any **OpenAI-compatible text endpoint** (a URL), the
pluggable-provider design as every other LLM lane. It does not own or require a model server.
This directory stands up a known-good local CPU one so you can exercise the
retrieve -> augment -> generate flow end to end.

If you already run llama.cpp / vLLM / LM Studio / Ollama / a hosted API, **skip this** and
point madosho at yours (see "Wiring madosho" below).

This is the **text** counterpart to `services/vision-server`. Kept separate on purpose:
vision-server is GPU (vision judges for the extraction comparison); this is CPU (small
text models for answering queries).

## What it is

The **official llama.cpp server image** (`ghcr.io/ggml-org/llama.cpp:server`, CPU build)
in **router mode**, serving **two small instruct models** behind one endpoint
(`preset.ini`):

| model name | what it is | quant | size |
|------------|------------|-------|------|
| `llama-3.2-1b` | Llama 3.2 1B Instruct | `Q4_K_M` | ~0.8 GB |
| `qwen2.5-1.5b` | Qwen2.5 1.5B Instruct | `Q4_K_M` | ~1.0 GB |

In router mode, llama-server loads whichever model a request names and unloads the
previous one (`--models-max 1`), so you run **one at a time** automatically -- no
third-party wrapper, no manual start/stop. Both resolve from your shared HuggingFace
cache, so this serves the GGUFs you already pulled with `hf download` (no duplicate
downloads). CPU-only: a few seconds per short answer, which is all you need to watch
the flow.

## Quickstart

The madosho stack must be up first -- this container joins its network (`madosho_default`):

```bash
cd /path/to/madosho && docker compose up -d   # the madosho stack
cd services/llm-server
cp .env.example .env             # edit if your paths / uid differ
docker compose up -d
curl http://localhost:8096/v1/models     # includes llama-3.2-1b and qwen2.5-1.5b
docker compose logs --tail 50            # watch the first model load on first request
docker compose down
```

First request to a model triggers its load (and download, if not already cached).
Switching `model` in your request swaps to the other one.

### Test the answer path directly

```bash
curl http://localhost:8096/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "llama-3.2-1b",
  "messages": [{"role": "user", "content": "In one sentence, what is a corpus?"}]
}'
```

## Wiring madosho

madosho selects an LLM as `provider:model` and points it at an OpenAI-compatible base URL
via env (see `backend/madosho_server/settings.py`). Because this server joins the madosho
network, the query plane reaches it by **service name**, not the host port:

```bash
MADOSHO_LLM_API_BASE=http://llm-server:8080/v1
MADOSHO_LLM_API_KEY=sk-noop          # llama.cpp ignores it, but any-llm wants something
# then call with provider:model, e.g.  openai:llama-3.2-1b  /  openai:qwen2.5-1.5b
```

The dev override (`compose.override.yaml`) sets these on the `query` service, so a dev
`docker compose up` already points the answer lane here. For the deployable path
(`compose.yaml` alone) set them yourself in the shell / `.env`.

## Customizing

- **Different model / quant:** edit `hf-file` in `preset.ini` (pin the exact file -- the
  `repo:QUANT` tag shorthand does loose name-matching on multi-quant repos).
- **More models:** add another `[section]` to `preset.ini`; it shows up on the same
  endpoint.
- **Bigger / better answers:** swap in a 3B-7B instruct GGUF -- slower per token on CPU but
  the same wiring.

## Notes

- The container runs as `${PUID}:${PGID}` (default `1000:1000`) so cache files stay yours.
- CPU build (`:server` image) -- no GPU needed, no NVIDIA runtime.
- **Router mode is marked experimental** by llama.cpp ("not for untrusted environments")
  -- fine here: only the madosho network and your localhost can reach it. `/v1/models`
  also auto-lists other GGUFs already in your HF cache; the two preset names above are
  the tuned entries.
- Intentionally minimal. This exists to learn and exercise the flow, not to be a
  production inference server.
