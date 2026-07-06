#!/usr/bin/env python3
"""Smoke-test the madosho agent pack.

Default run (no LLM): parse both skills, then prove madosho-cli connectivity
(`agent-tools` + `list-corpora`). With --with-llm, additionally fire a short
server-side research run via research_trigger.py. Stdlib only. Run from the pack dir
against a running stack (set MADOSHO_QUERY_URL / MADOSHO_CONTROL_URL if not local).

Env vars:
  MADOSHO_QUERY_URL    default http://localhost:8001
  MADOSHO_CONTROL_URL  default http://localhost:8000
  MADOSHO_API_KEY      bearer key for the madosho stack (required when
                       MADOSHO_AUTH_ENABLED is on, which is the default).
                       The madosho-cli subprocess inherits the calling
                       shell's env, so export MADOSHO_API_KEY before running."""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

_PACK = pathlib.Path(__file__).resolve().parent
_SKILLS = ("madosho-search", "madosho-research")


def _read_frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, fm, _ = text.split("---\n", 2)
    front = {}
    for line in fm.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, val = line.partition(":")
            front[key.strip()] = val.strip()
    return front


def check_skills() -> list[str]:
    """Return one 'name: description' line per skill (proves both parse)."""
    out = []
    for name in _SKILLS:
        front = _read_frontmatter(_PACK / name / "SKILL.md")
        out.append(f"{front.get('name')}: {front.get('description', '')[:80]}...")
    return out


def _cli(*args: str) -> dict:
    proc = subprocess.run(["madosho-cli", *args, "--json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"madosho-cli {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="agent_pack_demo.py", description="Smoke-test the madosho agent pack.")
    ap.add_argument("--with-llm", action="store_true", dest="with_llm",
                    help="also fire a server-side research run (needs an LLM provider)")
    ap.add_argument("--corpus", default=None, help="corpus for the --with-llm run")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)

    print("skills:")
    for line in check_skills():
        print(f"  - {line}")

    print("\nmadosho-cli connectivity (no LLM):")
    manifest = _cli("agent-tools")
    names = [t["name"] for t in manifest["tools"]]
    print(f"  agent-tools -> {len(names)} tools: {', '.join(names)}")
    corpora = _cli("list-corpora")
    print(f"  list-corpora -> {len(corpora['corpora'])} corpora")

    if args.with_llm:
        if not (args.corpus and args.provider and args.model):
            print("--with-llm needs --corpus, --provider, --model", file=sys.stderr)
            return 2
        print("\nserver-side research run (--with-llm):")
        rc = subprocess.call([sys.executable, str(_PACK / "research_trigger.py"),
                              "--corpus", args.corpus, "--provider", args.provider,
                              "--model", args.model, "--prompt",
                              "Give a one-paragraph overview of this corpus."])
        return rc
    print("\nOK (no-LLM checks passed). Re-run with --with-llm for the research run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
