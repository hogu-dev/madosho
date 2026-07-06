#!/usr/bin/env python3
"""madosho as just the retriever.

madosho returns the ranked chunks and stops. This CLI then makes its OWN path to
an LLM: it builds its own prompt from the chunks and calls the llm-server
directly. madosho is not involved past retrieval. Pass --no-llm to stop at
retrieval and just print the chunks (madosho as a pure retriever / agent tool).

    python retrieve.py "how many engines on the S-IC?"
    python retrieve.py --no-llm "..."         # pure retrieval, no LLM call
    python retrieve.py --corpus test --model llama-3.2-1b "..."

Talks to the query service (retrieval) and the llm-server (generation) over HTTP.
Stdlib only, no pip install. A real app would likely use the `openai` SDK for
step 2; raw HTTP here keeps the path visible.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

# Host ports from compose: query service on 8001, the example llm-server on 8096.
QUERY_URL = os.environ.get("MADOSHO_QUERY_URL", "http://localhost:8001")
LLM_URL = os.environ.get("MADOSHO_LLM_URL", "http://localhost:8096/v1")
# Auth is on by default; a read-scoped key is enough for /query.
API_KEY = os.environ.get("MADOSHO_API_KEY")


def _auth() -> dict:
    return {"Authorization": "Bearer " + API_KEY} if API_KEY else {}


def post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers if headers is not None else _auth())})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"could not reach {url}: {e.reason}\n"
                 "is the stack up? (docker compose ps)")


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **_auth()})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"could not reach {url}: {e.reason}\n"
                 "is the stack up? (docker compose ps)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="madosho retrieves; you make your own path to the LLM.")
    ap.add_argument("question", nargs="?", help="omit with --list")
    ap.add_argument("--corpus", default="aerospace")
    ap.add_argument("--model", default="llama-3.2-1b")
    ap.add_argument("--no-llm", action="store_true",
                    help="stop at retrieval; just print the chunks")
    ap.add_argument("--top", type=int, default=4,
                    help="how many chunks to feed my own prompt")
    ap.add_argument("--list", action="store_true",
                    help="list the corpus's pipelines (names, slots, rating) and exit")
    ap.add_argument("--pipeline", action="append", default=[], metavar="NAME",
                    help="answer a document through this pipeline (repeatable; overrides effective)")
    args = ap.parse_args()

    if args.list:
        rows = get_json(f"{QUERY_URL}/corpora/{args.corpus}/pipelines")
        for p in rows:
            s = p.get("slots") or {}
            flag = "  [effective]" if p.get("effective") else ""
            print(f"{p['name']:<22} extract={s.get('extract')!s:<10} "
                  f"chunk={s.get('chunk')!s:<10} index={s.get('index')!s:<10} "
                  f"rating {p.get('rating', 0):>4}  {p.get('status')}{flag}")
        return
    if not args.question:
        sys.exit("a question is required (or pass --list)")

    # 1) Ask madosho for retrieval only: no `llm` field -> hits, no answer.
    print(f"[retrieve-only] madosho retrieves from '{args.corpus}', I take it from there\n")
    payload = {"corpus": args.corpus, "prompt": args.question}
    if args.pipeline:
        payload["pipelines"] = args.pipeline
    hits = post_json(f"{QUERY_URL}/query", payload).get("hits", [])
    print(f"retrieved {len(hits)} chunks:")
    for i, h in enumerate(hits, 1):
        snippet = " ".join((h.get("text") or "").split())[:100]
        print(f"  [{i}] {h.get('citation')}  (score {h.get('score', 0):.3f})  {snippet}...")

    if args.no_llm or not hits:
        return

    # 2) Make my OWN path to the LLM: build my own prompt from the top chunks and
    #    call the llm-server directly (OpenAI-compatible). My prompt, my rules -
    #    madosho never sees this step.
    top = hits[: args.top]
    context = "\n\n".join(f"[{i}] {h['text']}" for i, h in enumerate(top, 1))
    my_prompt = textwrap.dedent(f"""\
        Answer the question using only the sources below. Cite them like [1].

        Sources:
        {context}

        Question: {args.question}""")

    print(f"\n-> built my own prompt from the top {len(top)} chunks, "
          f"calling {args.model} myself\n")
    completion = post_json(
        f"{LLM_URL}/chat/completions",
        {"model": args.model, "messages": [{"role": "user", "content": my_prompt}]},
        headers={"Authorization": "Bearer sk-noop"})
    print("my LLM says:")
    print(completion["choices"][0]["message"]["content"].strip())


if __name__ == "__main__":
    main()
