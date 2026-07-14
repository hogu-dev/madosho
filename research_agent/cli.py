"""Standalone CLI: fire a research run from a terminal against a conforming CLI.

    python -m research_agent run \
        --prompt "How does the AFTI/F-16 handle sensor failures?" \
        --cli madosho-cli --provider openai --model gpt-x

Doubles as the manual-test harness and the basis for the opt-in live e2e. The
LLM api-key comes from --api-key or RESEARCH_AGENT_API_KEY and is never printed.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import run
from .llm import AnyLlmClient
from .tools import CliToolProvider
from .types import LlmEndpoint, RunBudget


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="research_agent",
                                 description="Run a research agent over a corpus via a CLI.")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="run a research agent and print a cited report")
    p.add_argument("--prompt", required=True, help="the research question")
    p.add_argument("--cli", default="madosho-cli",
                   help="CLI invocation to drive (whitespace-split; default: madosho-cli)")
    p.add_argument("--provider", default=os.environ.get("RESEARCH_AGENT_PROVIDER"),
                   help="LLM provider (env: RESEARCH_AGENT_PROVIDER)")
    p.add_argument("--model", default=os.environ.get("RESEARCH_AGENT_MODEL"),
                   help="LLM model (env: RESEARCH_AGENT_MODEL)")
    p.add_argument("--api-base", default=os.environ.get("RESEARCH_AGENT_API_BASE"),
                   help="LLM API base URL (env: RESEARCH_AGENT_API_BASE)")
    p.add_argument("--api-key", default=os.environ.get("RESEARCH_AGENT_API_KEY"),
                   help="LLM API key (env: RESEARCH_AGENT_API_KEY); never printed")
    p.add_argument("--budget-chars", type=int, default=100_000, dest="budget_chars")
    p.add_argument("--max-rounds", type=int, default=8, dest="max_rounds")
    p.add_argument("--autonomous-md", default=None, dest="autonomous_md",
                   help="path to an autonomous.md override (default: the shipped one)")
    p.add_argument("--kb", default=None,
                   help="path to an llmkb KB the agent may read/write via kb_ tools")
    p.add_argument("--out", default=None, help="write the report markdown to this path")
    p.set_defaults(func=cmd_run)
    return ap


def _make_tools(args):
    base = CliToolProvider(args.cli.split())
    if getattr(args, "kb", None):
        from .tools import LlmkbToolProvider, MultiToolProvider
        return MultiToolProvider([base, LlmkbToolProvider(args.kb)])
    return base


def _make_endpoint(args) -> LlmEndpoint:
    return LlmEndpoint(provider=args.provider, model=args.model,
                       api_key=args.api_key, api_base=args.api_base)


def cmd_run(args) -> int:
    if not args.provider or not args.model:
        print("error: --provider and --model are required "
              "(or set RESEARCH_AGENT_PROVIDER / RESEARCH_AGENT_MODEL)", file=sys.stderr)
        return 2
    autonomous_md = None
    if args.autonomous_md:
        with open(args.autonomous_md, encoding="utf-8") as fh:
            autonomous_md = fh.read()
    tools = _make_tools(args)
    llm = AnyLlmClient(_make_endpoint(args))
    budget = RunBudget(max_context_chars=args.budget_chars, max_rounds=args.max_rounds)
    try:
        report = run(args.prompt, tools=tools, llm=llm,
                     autonomous_md=autonomous_md, budget=budget)
    except Exception as e:   # surface any failure as a non-zero exit, never a traceback dump
        print(f"research run failed: {e}", file=sys.stderr)
        return 1
    print(report.markdown)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report.markdown)
    print(f"\n[stop reason: {report.stop_reason}; {len(report.citations)} citation(s); "
          f"{len(report.run_log)} log entries]", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
