#!/usr/bin/env python3
"""Walk madosho's chat-frontend doors end to end.

Companion runnable for the README in this directory. Proves both integration styles a
chat frontend (Open WebUI) uses, against the running stack:

  Mode B (context source / OpenAPI tool server, NO LLM on madosho's side):
    * GET  :8088/openapi.json   - operationIds match the agent-tools manifest
    * POST :8088/search         - real retrieval (ranked, cited chunks; no LLM)

  Mode A (proxy / the OpenAI shim):
    * GET  :8001/v1/models                 - madosho's virtual models
    * POST :8001/v1/chat/completions       - with --with-llm: non-stream + stream

The Mode B walk and /v1/models need only the stack up with a corpus indexed - NO
LLM provider. The proxy chat (Mode A generation) is behind --with-llm because it
needs a provider configured and a virtual model registered.

    python chat_frontends_demo.py
    python chat_frontends_demo.py --corpus demo
    python chat_frontends_demo.py --with-llm --model <virtual-model>

Env vars:
  MADOSHO_QUERY_URL      default http://localhost:8001
  MADOSHO_TOOLSERVER_URL default http://localhost:8088
  MADOSHO_API_KEY        bearer key for the madosho stack (required when
                         MADOSHO_AUTH_ENABLED is on, which is the default);
                         sent as Bearer to both the query plane and the tool
                         server (the tool server forwards it to the backend)

Talks to the running services over HTTP. Stdlib only, no pip install.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

QUERY_URL = os.environ.get("MADOSHO_QUERY_URL", "http://localhost:8001")
TOOLSERVER_URL = os.environ.get("MADOSHO_TOOLSERVER_URL", "http://localhost:8088")

# Auth key - sent as Bearer when set. Auth defaults ON in the stack; set this
# to a valid madosho key before running (see docs/AUTH.md for how to create one).
_API_KEY = os.environ.get("MADOSHO_API_KEY")

_AUTH_HINT = (
    "\nhint: received HTTP {status} - auth is ON by default in this stack.\n"
    "  Set MADOSHO_API_KEY to a valid madosho key and re-run.\n"
    "  See docs/AUTH.md for key creation, or compose.override.yaml to disable auth locally."
)


def _request(url, payload=None, raw=False):
    """GET (payload None) or POST JSON. Sends Bearer auth when MADOSHO_API_KEY is set.
    Exits non-zero on 401/403 with a MADOSHO_API_KEY hint."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if _API_KEY:
        headers["Authorization"] = "Bearer " + _API_KEY
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return body if raw else json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code in (401, 403):
            sys.exit(f"HTTP {e.code} from {url}" + _AUTH_HINT.format(status=e.code))
        try:
            return ("error", e.code, json.loads(body))
        except json.JSONDecodeError:
            return ("error", e.code, body)
    except urllib.error.URLError as e:
        sys.exit(f"could not reach {url}: {e.reason}\n"
                 "is the stack up? (docker compose ps from the repo root)")


def _h(title):
    print(f"\n=== {title} ===")


def mode_b(corpus):
    _h("Mode B: madosho as an OpenAPI tool server (no LLM on madosho's side)")
    spec = _request(f"{TOOLSERVER_URL}/openapi.json")
    ops = sorted(p["post"]["operationId"] for p in spec["paths"].values()
                 if "post" in p)
    print(f"tool server publishes operationIds: {ops}")
    print("  (Open WebUI registers this URL under Admin Settings > Tools)")

    _h(f"Mode B: POST /search over corpus '{corpus}' - the model's retrieval call")
    out = _request(f"{TOOLSERVER_URL}/search",
                   {"corpus": corpus, "query": "what is this about?"})
    if isinstance(out, tuple):
        print(f"  (search returned {out[1]}: {out[2]}) - is '{corpus}' indexed?")
        return
    hits = out.get("hits", [])
    print(f"got {len(hits)} chunks the client's model would read:")
    for i, h in enumerate(hits[:3], 1):
        snippet = " ".join((h.get("text") or "").split())[:80]
        print(f"  [{i}] {h.get('citation')}  {snippet}")


def mode_a_models():
    _h("Mode A: GET /v1/models - madosho's virtual models (the proxy dropdown)")
    out = _request(f"{QUERY_URL}/v1/models")
    if isinstance(out, tuple):
        print(f"  (models returned {out[1]}: {out[2]})")
        return []
    ids = [m["id"] for m in out.get("data", [])]
    print(f"virtual models: {ids or '(none registered - add one in Settings)'}")
    return ids


def mode_a_chat(model):
    _h(f"Mode A: POST /v1/chat/completions (model '{model}') - non-stream")
    out = _request(f"{QUERY_URL}/v1/chat/completions",
                   {"model": model, "messages": [
                       {"role": "user", "content": "what are the key terms?"}]})
    if isinstance(out, tuple):
        print(f"  (chat returned {out[1]}: {out[2]})")
        return
    content = out["choices"][0]["message"]["content"]
    print(content[:400])
    print("  ^ note the 'Sources:' citation footer the shim appends")

    _h(f"Mode A: POST /v1/chat/completions (model '{model}') - stream")
    raw = _request(f"{QUERY_URL}/v1/chat/completions",
                   {"model": model, "messages": [
                       {"role": "user", "content": "what are the key terms?"}],
                    "stream": True}, raw=True)
    datas = [ln[len("data: "):] for ln in raw.splitlines() if ln.startswith("data: ")]
    print(f"streamed {len(datas)} SSE events; last is {datas[-1] if datas else '(none)'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="demo")
    ap.add_argument("--with-llm", action="store_true",
                    help="also exercise the proxy chat (needs a provider + virtual model)")
    ap.add_argument("--model", default=None,
                    help="virtual model name for --with-llm (default: first registered)")
    args = ap.parse_args(argv)

    mode_b(args.corpus)
    ids = mode_a_models()
    if args.with_llm:
        model = args.model or (ids[0] if ids else None)
        if not model:
            print("\n(--with-llm: no virtual model registered; skipping proxy chat)")
        else:
            mode_a_chat(model)
    print("\nDone. See examples/chat-frontends/README.md for the Open WebUI walkthrough.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
