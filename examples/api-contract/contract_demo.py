#!/usr/bin/env python3
"""Walk madosho's HTTP contract end to end.

The companion runnable for the README in this directory. It calls every surface
of the contract and prints the typed, clean responses, so "the contract works" is
something you watch, not something you take on faith:

  * both planes' /health and where their live schema lives (/docs, /openapi.json)
  * the control plane's typed corpus list
  * native /query as a RETRIEVER (no `llm` in the request) - typed hits, basename'd source
  * the OpenAI shim: /v1/models, and (with --with-llm) /v1/chat/completions
    non-stream + stream
  * native /query as a PROXY (`llm` in the request; madosho drives the model) - with --with-llm
  * the two error envelopes side by side: native {"detail": ...} vs shim
    {"error": {...}}

The core walk needs only the stack up with a corpus indexed - NO LLM provider.
The generate paths (proxy + shim chat) are behind --with-llm because they
need a provider configured and, for the shim, a virtual model registered.

    python contract_demo.py
    python contract_demo.py --corpus test
    python contract_demo.py --with-llm --model llama-3.2-1b

Env vars:
  MADOSHO_CONTROL_URL   default http://localhost:8000
  MADOSHO_QUERY_URL     default http://localhost:8001
  MADOSHO_API_KEY       bearer key for the madosho stack (required when
                        MADOSHO_AUTH_ENABLED is on, which is the default)

Talks to the running services over HTTP. Stdlib only, no pip install.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Host ports from compose: control plane on 8000, query plane on 8001.
CONTROL_URL = os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000")
QUERY_URL = os.environ.get("MADOSHO_QUERY_URL", "http://localhost:8001")

# Auth key - sent as Bearer when set. Auth defaults ON in the stack; set this
# to a valid madosho key before running (see docs/AUTH.md for how to create one).
_API_KEY = os.environ.get("MADOSHO_API_KEY")

_AUTH_HINT = (
    "\nhint: received HTTP {status} - auth is ON by default in this stack.\n"
    "  Set MADOSHO_API_KEY to a valid madosho key and re-run.\n"
    "  See docs/AUTH.md for key creation, or compose.override.yaml to disable auth locally."
)


def _request(url: str, payload: dict | None = None, raw: bool = False):
    """GET (payload None) or POST JSON. Returns parsed JSON, or on an HTTP error
    returns ('error', status, body) so a caller can show the error envelope.
    Exits non-zero on 401/403 with an MADOSHO_API_KEY hint."""
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
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return ("error", e.code, parsed)
    except urllib.error.URLError as e:
        sys.exit(f"could not reach {url}: {e.reason}\n"
                 "is the stack up? (docker compose ps from the repo root)")


def _h(title: str) -> None:
    print(f"\n=== {title} ===")


def show_health_and_schema() -> None:
    _h("1. both planes are live, and publish their own OpenAPI schema")
    for name, base in (("control", CONTROL_URL), ("query", QUERY_URL)):
        health = _request(f"{base}/health")
        title = _request(f"{base}/openapi.json").get("info", {}).get("title")
        print(f"  {name:<7} {base}  health={health.get('status')}  "
              f"openapi.title={title!r}")
        print(f"          interactive docs: {base}/docs   schema: {base}/openapi.json")


def show_corpora() -> list[str]:
    _h("2. control plane: the typed corpus list (CorpusRead[])")
    rows = _request(f"{CONTROL_URL}/corpora")
    names = [c["name"] for c in rows]
    for c in rows:
        print(f"  corpus {c.get('id')!s:>3}  {c['name']}")
    if not names:
        print("  (no corpora yet - upload a document first)")
    return names


def show_retriever(corpus: str) -> None:
    _h(f"3. native /query as a RETRIEVER (no llm) on '{corpus}'")
    out = _request(f"{QUERY_URL}/query",
                   {"corpus": corpus, "prompt": "what is this about?"})
    if isinstance(out, tuple):
        return _show_error("native /query", out)
    hits = out.get("hits", [])
    print(f"  madosho returned {len(hits)} typed hits (QueryHitsResponse); no LLM was called.")
    for i, hsh in enumerate(hits[:3], 1):
        # `source` is the basename by contract; document_id is the real link.
        print(f"  [{i}] source={hsh.get('source')!r}  page={hsh.get('page')}  "
              f"doc={hsh.get('document_id')}  pipeline={hsh.get('pipeline')!r}  "
              f"score={hsh.get('score', 0):.3f}")
    if hits:
        print("       ^ note source is a clean filename, not a /data/filestore/... path")


def show_shim_models() -> list[str]:
    _h("4. OpenAI shim: GET /v1/models (madosho's virtual models)")
    out = _request(f"{QUERY_URL}/v1/models")
    ids = [m["id"] for m in out.get("data", [])]
    print(f"  object={out.get('object')!r}  models={ids or '(none registered)'}")
    return ids


def show_proxy(corpus: str, model: str) -> None:
    _h(f"5. native /query as a PROXY (llm=openai:{model}) on '{corpus}'")
    out = _request(f"{QUERY_URL}/query",
                   {"corpus": corpus, "prompt": "give a one sentence summary.",
                    "llm": f"openai:{model}"})
    if isinstance(out, tuple):
        return _show_error("native /query (proxy)", out)
    answer = (out.get("answer") or "").split("\nSources:")[0].rstrip()
    print(f"  answer: {answer or '(empty)'}")
    cites = out.get("citations", [])
    for i, c in enumerate(cites[:3], 1):
        print(f"  source [{i}] {c.get('citation')!r}")   # basename'd clean label
    if out.get("usage"):
        print(f"  usage: {out['usage']}")


def show_shim_chat(model: str, stream: bool) -> None:
    label = "stream" if stream else "non-stream"
    _h(f"6. OpenAI shim: POST /v1/chat/completions ({label}) model={model!r}")
    payload = {"model": model, "stream": stream,
               "messages": [{"role": "user", "content": "one sentence summary?"}]}
    if not stream:
        out = _request(f"{QUERY_URL}/v1/chat/completions", payload)
        if isinstance(out, tuple):
            return _show_error("shim chat", out)
        # OpenAI ChatCompletion passthrough; madosho appends a Sources footer.
        content = (out.get("choices") or [{}])[0].get("message", {}).get("content", "")
        print(f"  object={out.get('object')!r}  model={out.get('model')!r}")
        print(f"  content (incl. Sources footer):\n    " + content.replace("\n", "\n    "))
        return
    # Streaming: read the raw SSE body and count chunk events.
    _stream_headers = {"Content-Type": "application/json"}
    if _API_KEY:
        _stream_headers["Authorization"] = "Bearer " + _API_KEY
    req = urllib.request.Request(
        f"{QUERY_URL}/v1/chat/completions", data=json.dumps(payload).encode(),
        headers=_stream_headers)
    try:
        with urllib.request.urlopen(req) as resp:
            events = [ln for ln in resp.read().decode().splitlines()
                      if ln.startswith("data:")]
        print(f"  received {len(events)} SSE 'data:' lines, ending in {events[-1] if events else '?'!r}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"HTTP {e.code} from shim stream" + _AUTH_HINT.format(status=e.code))
        _show_error("shim chat (stream)", ("error", e.code, e.read().decode(errors="replace")))


def show_error_envelopes(corpus: str) -> None:
    _h("7. the two error envelopes (one per plane)")
    native = _request(f"{QUERY_URL}/query", {"corpus": "no-such-corpus", "prompt": "x"})
    shim = _request(f"{QUERY_URL}/v1/chat/completions",
                    {"model": "no-such-model", "messages": [{"role": "user", "content": "x"}]})
    print("  native /query, unknown corpus ->")
    _show_error("native", native, indent=4)
    print("  shim /v1/chat/completions, unknown model ->")
    _show_error("shim", shim, indent=4)
    print("    native uses FastAPI's {\"detail\": ...}; the shim keeps OpenAI's "
          "{\"error\": {...}} (real OpenAI clients depend on it).")


def _show_error(where: str, result, indent: int = 4) -> None:
    pad = " " * indent
    if not (isinstance(result, tuple) and result[0] == "error"):
        print(f"{pad}(expected an error from {where}, got a success)")
        return
    _, status, body = result
    print(f"{pad}HTTP {status}  {json.dumps(body)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Walk madosho's HTTP contract and print the typed responses.")
    ap.add_argument("--corpus", default="demo",
                    help="corpus to query (create and index it first; see the README)")
    ap.add_argument("--with-llm", action="store_true",
                    help="also run the generate paths (proxy + shim chat); "
                         "needs a provider configured and a virtual model registered")
    ap.add_argument("--model", default="llama-3.2-1b",
                    help="provider model for the proxy path (--with-llm)")
    args = ap.parse_args()

    print("Walking the madosho HTTP contract (see examples/api-contract/README.md).")
    show_health_and_schema()
    names = show_corpora()
    corpus = args.corpus if args.corpus in names or not names else (names[0])
    show_retriever(corpus)
    model_ids = show_shim_models()
    if args.with_llm:
        show_proxy(corpus, args.model)
        vm = model_ids[0] if model_ids else None
        if vm:
            show_shim_chat(vm, stream=False)
            show_shim_chat(vm, stream=True)
        else:
            print("\n  (skipping shim chat: no virtual model registered - "
                  "add one in the web Settings, then re-run)")
    else:
        print("\n  (skipping the generate paths; pass --with-llm with a provider up)")
    show_error_envelopes(corpus)
    print("\nDone. Every surface above is a declared response model in /openapi.json.")


if __name__ == "__main__":
    main()
