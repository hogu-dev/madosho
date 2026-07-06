#!/usr/bin/env python3
"""Smoke-test madosho's MCP server over stdio.

Launches `python -m madosho_mcp` as an MCP stdio server, lists its tools, and calls
list-corpora (and a search if --corpus is given). No LLM needed - these are retrieval
tools. Needs a running madosho stack (set MADOSHO_QUERY_URL / MADOSHO_CONTROL_URL if it
is not on localhost).

Env vars:
  MADOSHO_QUERY_URL    default http://localhost:8001
  MADOSHO_CONTROL_URL  default http://localhost:8000
  MADOSHO_API_KEY      bearer key for the madosho stack (required when
                       MADOSHO_AUTH_ENABLED is on, which is the default).
                       This demo passes env=dict(os.environ) to the stdio
                       child, so the key propagates automatically - just
                       export it in the calling shell.

Unlike the other example packs this one is NOT stdlib-only: speaking MCP requires the
mcp client SDK (pip install "mcp>=1.8,<2"). That is inherent to the interface."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mcp_demo.py", description="Smoke-test the madosho MCP server over stdio.")
    ap.add_argument("--corpus", default=None,
                    help="corpus to search (optional; lists corpora if omitted)")
    ap.add_argument("--query", default="overview", help="search query for --corpus")
    args = ap.parse_args(argv)

    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError:
        print('this demo needs the mcp client SDK: pip install "mcp>=1.8,<2"',
              file=sys.stderr)
        return 2

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "madosho_mcp"], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("tools:", ", ".join(t.name for t in tools.tools))
                corpora = await session.call_tool("list-corpora", {})
                print("list-corpora isError:", corpora.isError)
                if corpora.content:
                    print(corpora.content[0].text)
                if args.corpus:
                    res = await session.call_tool(
                        "search", {"corpus": args.corpus, "query": args.query})
                    print("search isError:", res.isError)
                    if res.content:
                        print(res.content[0].text[:500])

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
