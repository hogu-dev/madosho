#!/usr/bin/env python3
"""madosho in the middle.

You ask a question; madosho retrieves the chunks, builds the prompt, calls the
LLM, and hands back the answer plus citations. This CLI never talks to an LLM
itself - madosho owns the whole path.

    python ask.py "how many engines on the S-IC?"
    python ask.py --corpus test --model llama-3.2-1b "..."
    python ask.py --show-prompt "..."        # also print the assembled prompt

Talks to the running query service over HTTP - the same /query endpoint the web
Playground uses. Stdlib only, no pip install.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Host ports from compose: the query service is published on 8001.
QUERY_URL = os.environ.get("MADOSHO_QUERY_URL", "http://localhost:8001")
# Auth is on by default; a read-scoped key is enough for /query.
API_KEY = os.environ.get("MADOSHO_API_KEY")


def _auth() -> dict:
    return {"Authorization": "Bearer " + API_KEY} if API_KEY else {}


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **_auth()})
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
        description="Ask madosho; it drives the LLM and returns the answer.")
    ap.add_argument("question", nargs="?", help="omit with --list")
    ap.add_argument("--corpus", default="aerospace")
    ap.add_argument("--model", default="llama-3.2-1b",
                    help="llm-server model; the query plane calls it as openai:<model>")
    ap.add_argument("--show-prompt", action="store_true",
                    help="also print the assembled prompt madosho sent the model")
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

    print(f"[ask] madosho retrieves from '{args.corpus}' + calls {args.model}, "
          "returns the answer\n")
    payload = {"corpus": args.corpus, "prompt": args.question,
               "llm": f"openai:{args.model}"}
    if args.pipeline:
        payload["pipelines"] = args.pipeline
    result = post_json(f"{QUERY_URL}/query", payload)

    if args.show_prompt:
        print("--- assembled prompt (the exact text madosho sent) ---")
        for m in result.get("messages", []):
            print(f"[{m['role']}]\n{m['content']}\n")
        print("--- end assembled prompt ---\n")

    # madosho appends a "Sources:" footer into the answer text; trim it, we print
    # the citations structured below.
    answer = (result.get("answer") or "").split("\nSources:")[0].rstrip()
    print("answer:")
    print(answer or "(empty)")

    cites = result.get("citations") or []
    if cites:
        print("\nsources:")
        for i, c in enumerate(cites, 1):
            print(f"  [{i}] {c.get('citation')}  (score {c.get('score', 0):.3f})")

    if result.get("usage"):
        print(f"\nusage: {result['usage']}")


if __name__ == "__main__":
    main()
