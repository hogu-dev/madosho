"""Tool discovery + invocation.

ToolProvider is the seam the loop talks to. The shipped CliToolProvider (Task 3)
drives any conforming CLI; tests use an in-test fake. to_openai_tools() adapts the
manifest into the tool list an OpenAI-format model expects; render_manifest()
produces a human-readable block for the system prompt.
"""
from __future__ import annotations

import json
import subprocess
from typing import Protocol

from .types import ToolSpec, ToolResult


class ToolProvider(Protocol):
    """How the loop discovers and invokes tools, independent of where they come from."""

    def manifest(self) -> list[ToolSpec]:
        ...

    def invoke(self, name: str, args: dict) -> ToolResult:
        ...


def to_openai_tools(specs: list[ToolSpec]) -> list[dict]:
    """Adapt ToolSpecs into the `tools=` list any_llm/OpenAI expects."""
    return [
        {"type": "function",
         "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
        for s in specs
    ]


def render_manifest(specs: list[ToolSpec]) -> str:
    """A compact bullet list of tool names + descriptions for the system prompt."""
    return "\n".join(f"- {s.name}: {s.description}" for s in specs)


_TIMEOUT_S = 120   # a single CLI call (one HTTP round trip) should be quick; cap so the loop cannot hang


class CliToolProvider:
    """Drives any CLI that emits an `agent-tools --json` manifest and accepts
    `--json` subcommands. Generic over the CLI - every consumer reuses it by
    passing its own CLI invocation (e.g. ["madosho-cli"] or ["python","-m","madosho_cli"]).
    Never raises into the loop: a failed call becomes a structured ToolResult."""

    def __init__(self, cli_argv: list[str]):
        self.cli_argv = list(cli_argv)
        self._invocations: dict[str, dict] = {}   # tool name -> invocation recipe

    def manifest(self) -> list[ToolSpec]:
        argv = self.cli_argv + ["agent-tools", "--json"]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"manifest call failed ({proc.returncode}): {proc.stderr.strip()}")
        raw = json.loads(proc.stdout)
        specs: list[ToolSpec] = []
        for entry in raw["tools"]:
            self._invocations[entry["name"]] = entry["invocation"]
            specs.append(ToolSpec(name=entry["name"],
                                  description=entry["description"],
                                  parameters=entry["parameters"]))
        return specs

    def invoke(self, name: str, args: dict) -> ToolResult:
        recipe = self._invocations.get(name)
        if recipe is None:
            return ToolResult(ok=False, error=f"unknown tool: {name!r}")
        try:
            # Model-supplied values are untrusted: they may only ever land as
            # argument VALUES, never be re-parsed as flags. Two guards: options
            # are =-joined into a single argv element, and positionals ride
            # behind a literal `--` (argparse's end-of-options marker), so a
            # value like "--force" stays data. Option NAMES are trusted (they
            # come from the CLI's own manifest, not the model).
            argv = list(self.cli_argv) + [recipe["subcommand"]]
            for opt in recipe.get("options", []):
                if opt in args and args[opt] is not None:
                    argv.append("--" + opt.replace("_", "-") + "=" + str(args[opt]))
            argv.append("--json")
            positionals = [str(args[p]) for p in recipe.get("positional", [])]
            if positionals:
                argv.append("--")
                argv.extend(positionals)
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"tool {name!r} timed out after {_TIMEOUT_S}s")
        except KeyError as e:
            return ToolResult(ok=False, error=f"tool {name!r} missing required arg: {e}")
        if proc.returncode != 0:
            return ToolResult(ok=False, error=(proc.stderr or proc.stdout or "").strip()
                              or f"tool {name!r} exited {proc.returncode}")
        try:
            return ToolResult(ok=True, data=json.loads(proc.stdout))
        except json.JSONDecodeError as e:
            return ToolResult(ok=False, error=f"bad JSON from tool {name!r}: {e}")
