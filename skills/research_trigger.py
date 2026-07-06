#!/usr/bin/env python3
"""Trigger madosho's OWN server-side research run and poll for the cited report.

This runs the same autonomous.md playbook as the host Mode-2 skill, but on madosho's
server (it has the LLM provider configured). Stdlib only. Example:

    python research_trigger.py --corpus demo --prompt "what are the termination terms?" \\
        --provider openai --model <your-model>

It POSTs /corpora/{id}/research, polls until the run finishes, and prints the report
plus its citations. Reads MADOSHO_CONTROL_URL (default http://localhost:8000) and
MADOSHO_API_KEY (auth is on by default; launching research needs a write-scoped key)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


API_KEY = os.environ.get("MADOSHO_API_KEY")


def _auth() -> dict:
    return {"Authorization": "Bearer " + API_KEY} if API_KEY else {}


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/json", **_auth()})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted, env-configured URL)
        return json.load(resp)


def _post_json(url: str, payload: dict):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **_auth()}, method="POST")
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return json.load(resp)


def resolve_corpus_id(name: str, *, control_base: str, get_json=_get_json) -> int:
    for c in get_json(f"{control_base}/corpora"):
        if c["name"] == name:
            return c["id"]
    raise SystemExit(f"corpus not found: {name!r}")


def launch(corpus_id: int, prompt: str, llm: dict, *, control_base: str,
           source: str = "rag", document_ids=None, budget_chars: int = 100_000,
           max_rounds: int = 8, post_json=_post_json) -> int:
    body = {"prompt": prompt, "source": source,
            "document_ids": document_ids or [], "budget_chars": budget_chars,
            "max_rounds": max_rounds, "llm": llm}
    run = post_json(f"{control_base}/corpora/{corpus_id}/research", body)
    return run["id"]


def poll(corpus_id: int, run_id: int, *, control_base: str, get_json=_get_json,
         sleep=time.sleep, interval: float = 2.0, timeout: float = 600.0) -> dict:
    waited = 0.0
    while True:
        run = get_json(f"{control_base}/corpora/{corpus_id}/research/{run_id}")
        if run.get("status") not in ("pending", "running"):
            return run
        if waited + interval > timeout:
            raise SystemExit(f"research run {run_id} did not finish within {timeout}s")
        sleep(interval)
        waited += interval


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="research_trigger.py",
        description="Trigger madosho's server-side research run and print the cited report.")
    ap.add_argument("--corpus", required=True, help="corpus name")
    ap.add_argument("--prompt", required=True, help="the research question")
    ap.add_argument("--provider", default=os.environ.get("RESEARCH_AGENT_PROVIDER"),
                    help="LLM provider (env: RESEARCH_AGENT_PROVIDER)")
    ap.add_argument("--model", default=os.environ.get("RESEARCH_AGENT_MODEL"),
                    help="LLM model (env: RESEARCH_AGENT_MODEL)")
    ap.add_argument("--source", default="rag", choices=["rag", "whole-text"])
    ap.add_argument("--budget-chars", type=int, default=100_000, dest="budget_chars")
    ap.add_argument("--max-rounds", type=int, default=8, dest="max_rounds")
    ap.add_argument("--control-url",
                    default=os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000"),
                    dest="control_url")
    ap.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)
    if not args.provider or not args.model:
        print("error: --provider and --model are required "
              "(or set RESEARCH_AGENT_PROVIDER / RESEARCH_AGENT_MODEL)", file=sys.stderr)
        return 2
    control = args.control_url.rstrip("/")
    llm = {"provider": args.provider, "model": args.model}
    try:
        corpus_id = resolve_corpus_id(args.corpus, control_base=control)
        run_id = launch(corpus_id, args.prompt, llm, control_base=control,
                        source=args.source, budget_chars=args.budget_chars,
                        max_rounds=args.max_rounds)
        print(f"launched research run {run_id} on corpus {args.corpus!r}; polling...",
              file=sys.stderr)
        run = poll(corpus_id, run_id, control_base=control,
                   interval=args.poll_interval, timeout=args.timeout)
    except urllib.error.URLError as e:
        print(f"could not reach madosho at {control}: {e}\n"
              "is the stack up? (docker compose ps)", file=sys.stderr)
        return 1
    if run.get("status") != "done":
        print(f"research run ended with status {run.get('status')!r}", file=sys.stderr)
        return 1
    markdown = run.get("report_markdown") or "(no report)"
    print(markdown)
    cites = run.get("citations") or []
    print(f"\n[{len(cites)} citation(s); status {run.get('status')}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
