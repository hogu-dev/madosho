# Example: local vision-server for madosho

This is an **example and sanity check**, not a required part of madosho.

madosho's extraction/vision lane talks to any **OpenAI-compatible vision endpoint** (a
URL), exactly like the text LLM lanes. It does not own or require a
model server. This directory just stands up a known-good local one so you can prove the
lane works, and gives you a template to run whatever vision model you want.

If you already run llama.cpp / vLLM / LM Studio / Ollama / a hosted API with a
vision-capable model, **skip this** and point madosho at yours (see "Wiring madosho"
below).

## What it is

The **official llama.cpp server image** (`ghcr.io/ggml-org/llama.cpp:server-cuda`) in
**router mode**, serving **two Gemma 4 vision judges** behind one endpoint (`preset.ini`):

| model name | what it is | quant | mmproj |
|------------|------------|-------|--------|
| `gemma-12b` | 12B "Unified", encoder-free omni | `UD-Q4_K_XL` (~7 GB) | 168 MB |
| `gemma-e4b` | native-small E4B, vision encoder | `Q8_0` (~8 GB) | 946 MB |

In router mode, llama-server loads whichever model a request names and unloads the
previous one (`--models-max 1`), so you run **one at a time** on a single GPU
automatically -- no third-party wrapper, no manual start/stop. Both models resolve from
your shared HuggingFace cache, so this serves the GGUFs you already pulled with
`hf download` (no duplicate downloads), and each model's mmproj auto-loads from its repo
so images work with no extra key.

## Quickstart

```bash
cp .env.example .env          # edit if your paths / uid differ
docker compose up -d
curl http://localhost:8095/v1/models     # should list gemma-12b and gemma-e4b
docker compose logs -f                   # watch the first model load on first request
docker compose down
```

First request to a model triggers its load (watch for the mmproj / clip line in the
logs = vision is live). Switching `model` in your request swaps the GPU to the other one.

### Test the vision path

Send a page image (base64 data URL) and ask for a transcription:

```bash
curl http://localhost:8095/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "gemma-12b",
  "messages": [{"role": "user", "content": [
    {"type": "text", "text": "Transcribe this page faithfully."},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,<...>"}}
  ]}]
}'
```

## Wiring madosho

madosho selects an LLM as `provider:model` and points it at an OpenAI-compatible base
URL via env (see `backend/madosho_server/settings.py`):

```bash
# madosho runs in containers, so it reaches this standalone server through the
# docker bridge, not localhost:
MADOSHO_LLM_API_BASE=http://host.docker.internal:8095/v1
MADOSHO_LLM_API_KEY=sk-noop          # llama.cpp ignores it, but any-llm wants something
# then call with provider:model, e.g.  openai:gemma-12b  /  openai:gemma-e4b
```

(For a curl test from the host itself, `http://localhost:8095/v1` works directly.)

In the service platform, vision endpoints live in the LLM-endpoint registry
(Settings -> LLM Endpoints); the `vision` parser transcribes pages through the
registry's vision-default. The stable contract is just "an OpenAI-compatible
base URL + a model name."

## Customizing

- **Different model / quant:** edit `hf-file` (or the `hf-repo` tag) in `preset.ini`
  (e.g. `gemma-4-E4B-it-Q4_K_M.gguf` for the faster E4B lane, or any other unsloth GGUF
  repo+quant).
- **More models:** add another `[section]` to `preset.ini`; it shows up on the same
  endpoint.
- **CPU offload / smaller VRAM:** lower `n-gpu-layers` in an entry to keep some layers on
  CPU (these models are dense, so there's no MoE-offload knob).

## Notes

- The container runs as `${PUID}:${PGID}` (default `1000:1000`) so cache files stay yours.
- Needs the NVIDIA container runtime (GPU). The `:server-cuda` image tracks llama.cpp
  master with vision support.
- **Router mode is marked experimental** by llama.cpp ("not for untrusted environments"),
  and the compose file publishes the port on ALL host interfaces on purpose (madosho's
  containers reach it via `host.docker.internal`, which a loopback-only bind would
  break). On a shared network, firewall the port from the LAN or restrict the bind
  yourself. One visible quirk: `/v1/models` also
  auto-lists other GGUFs already in your HF cache; the two preset names above are the
  tuned entries.
- **`gemma-12b` thinking is disabled in the preset:** the 12B Unified thinks by default
  (chain in `reasoning_content`, answer in `content`), which multiplies tokens on a
  per-page transcription lane. Remove the `chat-template-kwargs` line in `preset.ini` to
  re-enable it for judge work -- then give it token budget: a tight `max_tokens` cuts it
  off mid-think with empty `content`. `gemma-e4b` answers directly either way.
- This is intentionally minimal. For heavier setups (big MoE models, multi-GPU placement,
  speculative decoding) see a fuller llama.cpp wrapper -- madosho doesn't need any of it.
