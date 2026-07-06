# Example: US-origin LLM endpoint for the contextual chunker

This is an **example and sanity check**, not a required part of madosho.

madosho's index-time lane (contextual chunker, eval scorer, Scrying Answer) uses a
separate **text** LLM -- one call per chunk on ingest, plus on-demand eval/query calls.
This directory shows how to stand up a small Gemma 4 E-class text model locally using
the same official llama.cpp router-mode setup as `services/vision-server`. It seeds the
LLM endpoint registry on first boot via the env keys below.

If you already run llama.cpp / vLLM / LM Studio / Ollama / a hosted API with a
text-capable model, **skip this** and point the `MADOSHO_INDEX_LLM_*` vars at yours.

## Relationship to the other examples

| example | lane | model class | GPU? |
|---------|------|-------------|------|
| `services/llm-server` | query / answer | small CPU text | no |
| `services/vision-server` | extraction judge | Gemma 4 12B / E4B vision | yes |
| **`services/llm-endpoint`** | **index-time: contextual chunker + eval + Scrying** | **Gemma 4 E4B text** | **yes** |

The text E4B is the same base model as the vision E4B (one call per chunk, not per page
image), so if you already have vision-server running you can add a `gemma-4-e4b` entry
there and point this config's base URL at that server instead of running a second one.

**Vision capability included:** the seeded endpoint carries the vision capability as
well, so the same E4B server also drives the extraction head-to-head comparison with no
second server. On first boot, `MADOSHO_INDEX_LLM_*` seeds one row into the registry
with `supports_text=true`, `supports_vision=true`, and `is_vision_default=true`.

## What it is

The **official llama.cpp server image** (`ghcr.io/ggml-org/llama.cpp:server-cuda`, the
same image as vision-server) in **router mode**, serving one small Gemma 4 text model
behind an OpenAI-compatible `/v1` endpoint:

| model name | what it is | notes |
|------------|------------|-------|
| `gemma-4-e4b` | Gemma 4 E4B Instruct (text mode) | one call per chunk on ingest |

The `preset.ini` in this directory is a starting point. The exact HF repo + GGUF file
is an **example to adapt to your own llama.cpp setup** -- verify against your
already-downloaded GGUFs (use `ls $HF_HOME/hub/` or `hf download --dry-run`). The entry
pins the exact `hf-file` to avoid the MTP-head filename-matching trap (the note in
`preset.ini` explains it).

## Quickstart

Uses the same machinery as `services/vision-server`. Needs the NVIDIA runtime.

```bash
cd /path/to/madosho && docker compose up -d   # the madosho stack
cd services/llm-endpoint
cp .env.example .env                    # edit if your paths / uid differ
# edit the preset.ini hf-file to match your cache if needed, then:
docker compose up -d
curl http://localhost:8097/v1/models     # includes gemma-4-e4b
docker compose logs --tail 50            # watch the first load on first request
docker compose down
```

## Wiring madosho (seeding the registry on first boot)

Add to your local `.env` (never commit it -- it is gitignored):

```bash
MADOSHO_INDEX_LLM_PROVIDER=openai
MADOSHO_INDEX_LLM_MODEL=gemma-4-e4b
MADOSHO_LLM_API_BASE=http://host.docker.internal:8097/v1
MADOSHO_LLM_API_KEY=sk-noop     # llama.cpp ignores the value; any-llm requires something
```

On first boot, the app reads these four vars and inserts a row into the
`llm_endpoint` table (the LLM endpoint registry). After that the registry value is
authoritative -- you can update it in Settings -> LLM Endpoints without restarting.
The seeding is a one-time bootstrap: once the row exists, the env vars are ignored.

`MADOSHO_LLM_API_BASE` / `MADOSHO_LLM_API_KEY` are shared with the query/answer lane
and the research worker. Point them at whichever server handles those lanes in your
setup; the index-time lane routes through the same base URL (same server, `gemma-4-e4b`
model name selects the right preset entry).

## Customizing

- **Different model / quant:** edit `hf-file` in `preset.ini`. Any text model
  llama.cpp supports works here; Gemma 4 E4B is just the reference example.
- **Reuse vision-server:** its `gemma-e4b` entry is the same model (the mmproj adds
  vision without costing the text path anything) -- set `MADOSHO_LLM_API_BASE` to that
  server's URL instead; no second container needed.
- **Hosted provider:** set `MADOSHO_INDEX_LLM_PROVIDER=openai` (or `anthropic`, etc.),
  `MADOSHO_INDEX_LLM_MODEL` to the provider's model name, and put your key in the
  local `.env` only. Do not run this container at all.

## Notes

- One call per chunk on ingest: pick a model small enough to be fast but capable enough
  to write a useful context sentence. The 4B class is a reasonable default.
- The container runs as `${PUID}:${PGID}` (default `1000:1000`) so cache files stay yours.
- Needs the NVIDIA container runtime (GPU). Uses the same `:server-cuda` image as
  `services/vision-server`.
- **Router mode is marked experimental** by llama.cpp ("not for untrusted environments"),
  and the compose file publishes the port on ALL host interfaces on purpose (madosho's
  containers reach it via `host.docker.internal`, which a loopback-only bind would
  break). On a shared network, firewall the port from the LAN or restrict the bind
  yourself. `/v1/models` also auto-lists other
  GGUFs already in your HF cache; `gemma-4-e4b` is the tuned entry.
- This is intentionally minimal. For heavier setups run your own llama.cpp / vLLM --
  madosho only needs the URL.
