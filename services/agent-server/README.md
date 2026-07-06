# Example: local agent-server for madosho (US-developed tool-calling models)

This is an **example and sanity check**, not a required part of madosho.

madosho's research and answer lanes talk to any **OpenAI-compatible text endpoint** (a
URL). madosho does not own or require a model server. This directory stands up a
known-good local one whose models do **tool-calling** -- which the research-agent loop
needs -- using only **US-developed models**, served by the **official llama.cpp
server image** in router mode (no wrapper, tracks llama.cpp master so tool-call parsers
stay fresh). A CN-developed counterpart (Qwen-family server) ships in the separate
CN/other-source bundle (origin is recorded honestly and never gates anything -- see
`docs/COMPLIANCE.md`).

If you already run llama.cpp / vLLM / Ollama / a hosted API with a tool-calling model,
**skip this** and point madosho at yours (see "Wiring madosho" below).

## No weights, ever

This repo contains **no model weights**, and this example never builds a Docker image --
the container runs the stock upstream image unmodified. The first request that names a
model downloads its weights **into your own HuggingFace cache** (`~/.cache/huggingface`
by default, bind-mounted into the container). That cache is the only place weights ever
exist; deleting a model is HF-cache hygiene, not docker. Each download happens under the
model's own license (table below) -- by pulling a model you accept its terms; nothing
here changes madosho's Apache-2.0 license, because madosho ships only this config text,
never the weights.

## The models

All five behind one endpoint. llama-server runs in **router mode**: the request's
`model` field picks the model, and the server loads/unloads on demand with one resident
on the GPU at a time (`--models-max 1`). Speeds and VRAM below were measured on a 24 GB
card (RTX 4090 class).

| model name | org | license | download | VRAM | measured | notes |
|------------|-----|---------|----------|------|----------|-------|
| `granite-4.1-30b` | IBM (US) | Apache-2.0 | ~17.5 GB | ~19 GB | ~40 tok/s | **max quality** -- led its size class on BFCL v3 tool-calling; wants the card to itself |
| `gpt-oss-20b` | OpenAI (US) | Apache-2.0 | ~12 GB | **~7 GB** | ~39 tok/s | **free-GPU-space pick** -- MoE with experts partly on CPU (see the dial below); ONE tool call per response; reasoning effort pre-set HIGH |
| `granite-4.1-8b` | IBM (US) | Apache-2.0 | ~5 GB | ~6 GB | ~122 tok/s | low-VRAM pick, same tool-call format as the 30B |
| `nemotron-3-nano-4b` | NVIDIA (US) | **NVIDIA Open Model License** | ~2.5 GB | ~4 GB | ~203 tok/s | newest llama.cpp support of the five (smoke-tested OK); downloading = accepting NVIDIA's terms |
| `granite-4.1-3b` | IBM (US) | Apache-2.0 | ~2 GB | CPU-ok | - | smoke-test / CPU-only pick; proves the plumbing, weak for real research |

Granite 4.1 is on llama.cpp's documented known-good tool-calling list; `jinja = true`
(set per model in `preset.ini`) makes every entry emit native OpenAI `tool_calls`. All
five have been verified with a live forced tool call against this exact compose setup.

## The MoE dial: trading tokens/s for free VRAM

Mixture-of-Experts models activate only a few billion parameters per token, and
llama.cpp can keep expert weights in system RAM (`n-cpu-moe = N` keeps the first N
layers' experts on CPU; `cpu-moe = true` keeps all of them). The GPU then holds only
attention + the remainder -- that's what frees the card. Measured on `gpt-oss-20b`:

| setting | VRAM | speed |
|---------|------|-------|
| no offload | ~13 GB | fastest |
| `n-cpu-moe = 12` (shipped default) | ~7 GB | ~39 tok/s |
| `cpu-moe = true` | ~2.4 GB | ~21 tok/s |

Tune N in `preset.ini` to taste. Dense models (the Granites, Nemotron here) have no
expert weights to offload -- their VRAM knobs are quant size and `ctx-size` only, which
is why `granite-4.1-30b` simply needs a mostly-idle 24 GB card.

## Quickstart

The madosho stack must already be up (this joins its network `madosho_default`).

```bash
cp .env.example .env          # edit if your paths / uid differ
docker compose up -d
curl http://localhost:8098/v1/models   # lists the preset models (plus anything cached, see Notes)
docker compose logs --tail 50          # watch the first model download + load on first request
docker compose down
```

The first request to a model triggers its download (once, into your shared cache) and
GPU load. Naming a different `model` in your request swaps the GPU to that one.

## Wiring madosho

Because this container **joins the madosho network**, the worker reaches it by name at
`http://agent-server:8080/v1` -- no host-gateway juggling. Point the worker's LLM env
there and pick a model:

```bash
# in the repo-root .env (the worker reads these), or your compose override:
MADOSHO_LLM_API_BASE=http://agent-server:8080/v1
MADOSHO_LLM_API_KEY=sk-noop        # llama.cpp ignores it, but any-llm wants something
# then start a research run with provider=openai and model=granite-4.1-30b
#   (or any other name from the table)
```

The stable contract is just "an OpenAI-compatible base URL + a model name."

## No GPU?

The default image is `:server-cuda` and needs the NVIDIA container runtime. On a
CPU-only box:

- Swap the image in `docker-compose.yml` to `ghcr.io/ggml-org/llama.cpp:server` and
  remove the `deploy.resources` block.
- Use **`granite-4.1-3b` only** -- everything larger is unusably slow on CPU.
- **Limitations:** expect tens of seconds to minutes per agent step, and weaker
  tool-calling than a GPU model gives. This path is for proving the loop runs, not for
  real research.

(For fast CPU testing of the *query / answer* lane specifically, `services/llm-server`
already serves tiny 1-2 B models.)

## Customizing

- **Different quant:** change the `:Q4_K_M` tag in an entry's `hf-repo` value (e.g.
  `:Q5_K_M` for a bit more quality, a smaller quant for less VRAM).
- **More models:** add a section to `preset.ini`; it shows up on the same endpoint. Any
  GGUF with a tool-use chat template works.
- **More VRAM headroom:** raise `n-cpu-moe` on MoE entries (see the dial above); lower
  `ctx-size` or pick a smaller quant on dense ones.
- **Bigger card (>=32 GB):** raise `ctx-size` on the 30B entry (8192 is the 24 GB fit).

## Notes / limitations

- Runs as `${PUID}:${PGID}` (default `1000:1000`) so cache files stay owned by you.
- **One model at a time:** `--models-max 1` swaps on the GPU; the first request after a
  switch pays a cold load (~tens of seconds).
- **Router mode is marked experimental by llama.cpp** and "not recommended in untrusted
  environments". Fine here: only the madosho network and your localhost can reach it.
  If it ever misbehaves after an image update, pin the image to a known-good digest.
- **The endpoint also lists other GGUFs already in your HF cache** (router mode
  auto-discovers them). Harmless -- the preset entries (starred in the logs) are the
  configured, tested ones.
- **`gpt-oss-20b` emits at most one tool call per response** -- agent loops still work,
  they just take more round trips. Its reasoning effort is pre-set to HIGH via
  `chat-template-kwargs`; lower it if you want speed over call reliability.
- **`nemotron-3-nano-4b` is the newest llama.cpp citizen here** (its 30B-A3B sibling is
  currently broken upstream, ggml-org/llama.cpp#20570, and is deliberately not listed).
  It passed the tool-call smoke test; if it misbehaves after an image update, that's the
  first suspect.
- Intentionally minimal. For heavier setups (multi-GPU placement, speculative decoding)
  use a fuller llama.cpp setup -- madosho doesn't need any of it.
