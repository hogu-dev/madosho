#!/usr/bin/env python3
"""Run every madosho external-interface demo in sequence.

One command that exercises all four external doors against a running stack:
  api-contract    native /query + OpenAI shim   examples/api-contract/contract_demo.py
  chat-frontends  toolserver + proxy chat       examples/chat-frontends/chat_frontends_demo.py
  mcp             MCP server (stdio)            examples/mcp/mcp_demo.py
  agent-skills    CLI + agent skills            skills/agent_pack_demo.py

This is a SEQUENCER, not a re-implementation: it shells out to each pack's own demo
(the single runnable source of truth) and prints one PASS/FAIL line per interface.

Default (no --with-llm) runs the headless retrieval paths - no LLM provider needed.
--with-llm forwards the flag (plus --corpus/--provider, and --model as the RAW
provider model) to the demos that accept it. The chat-frontends proxy chat
self-resolves the first registered virtual model, so a single `--model <raw>` drives
every generate path. The per-demo generate paths still differ in depth, so for the
fullest coverage run each pack demo directly (see the README in this directory).
Needs a running stack (set MADOSHO_QUERY_URL /
MADOSHO_CONTROL_URL / MADOSHO_TOOLSERVER_URL / MADOSHO_API_KEY if it is not on a
dev-local override stack; MADOSHO_API_KEY is required when MADOSHO_AUTH_ENABLED is on,
which is the default - export it before running so each child demo inherits it)."""
from __future__ import annotations

import argparse
import dataclasses
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


@dataclasses.dataclass(frozen=True)
class Demo:
    label: str            # human label, e.g. "api-contract"
    path: str             # relative to the repo root, e.g. "examples/api-contract/contract_demo.py"
    flags: frozenset      # passthrough flags this demo accepts


# --model here is the RAW provider model (e.g. gemma-4-e4b): the api-contract proxy
# and the agent-skills research run pass it straight to the LLM endpoint.
# chat-frontends is deliberately NOT given --model -- its proxy chat takes a *virtual*
# model name (a different namespace entirely), so it self-resolves to the first model
# registered in Settings. Forwarding one raw --model to all four would silently 404
# the proxy chat or hard-fail the research run; keeping chat-frontends off the
# passthrough lets a single `--model <raw>` drive every generate path correctly.
# (The shim-chat sub-path also auto-resolves the registered virtual model,
# independent of --model.)
DEMOS = [
    Demo("api-contract", "examples/api-contract/contract_demo.py",
         frozenset({"corpus", "model", "with_llm"})),
    Demo("chat-frontends", "examples/chat-frontends/chat_frontends_demo.py",
         frozenset({"corpus", "with_llm"})),
    Demo("mcp", "examples/mcp/mcp_demo.py",
         frozenset({"corpus"})),
    Demo("agent-skills", "skills/agent_pack_demo.py",
         frozenset({"corpus", "model", "provider", "with_llm"})),
]


def build_argv(demo: Demo, opts: argparse.Namespace) -> list[str]:
    """python <script> + only the passthrough flags this demo accepts and the user
    supplied. Pure + testable - no IO."""
    argv = [sys.executable, str(REPO / demo.path)]
    for name in ("corpus", "model", "provider"):
        value = getattr(opts, name, None)
        if name in demo.flags and value is not None:
            argv += [f"--{name}", str(value)]
    if "with_llm" in demo.flags and getattr(opts, "with_llm", False):
        argv.append("--with-llm")
    return argv


def run_demo(demo: Demo, opts: argparse.Namespace) -> tuple[str, bool, str]:
    """Run one demo as a subprocess. Returns (label, passed, output_tail). A missing
    script or a non-zero exit is a FAIL for that interface, never an orchestrator crash."""
    script = REPO / demo.path
    if not script.exists():
        return (demo.label, False, f"demo script not found: {script}")
    proc = subprocess.run(build_argv(demo, opts), capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return (demo.label, proc.returncode == 0, "\n    ".join(tail))


def summarize(results: list[tuple[str, bool, str]]) -> int:
    """Print a PASS/FAIL table + summary. Side-effecting (prints); returns 0 iff every interface passed."""
    print("\n=== madosho external-interface demo summary ===")
    passed = 0
    for label, ok, tail in results:
        mark = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  [{mark}] {label}")
        if not ok and tail:
            print(f"    {tail}")
    print(f"\n{passed}/{len(results)} interfaces passed")
    return 0 if passed == len(results) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="demo_all.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-llm", action="store_true", dest="with_llm",
                    help="also run the demos' generate paths (needs a provider configured)")
    ap.add_argument("--corpus", default=None,
                    help="override every demo's default corpus for a uniform run")
    ap.add_argument("--model", default=None,
                    help="RAW provider model (e.g. gemma-4-e4b) for the api-contract "
                         "proxy + the agent-skills research run; chat-frontends "
                         "self-resolves its registered virtual model")
    ap.add_argument("--provider", default=None,
                    help="provider passthrough (agent-skills --with-llm)")
    opts = ap.parse_args(argv)

    results = []
    for demo in DEMOS:
        print(f"\n--- {demo.label}: {' '.join(build_argv(demo, opts))} ---")
        results.append(run_demo(demo, opts))
    return summarize(results)


if __name__ == "__main__":
    raise SystemExit(main())
