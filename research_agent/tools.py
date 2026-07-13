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
        if recipe is None and not self._invocations:
            # invoke() before manifest(): load the recipe table on first use so a
            # DIRECT invoke works instead of silently failing. The orchestrator's
            # mechanical corpus-size lookup (list_corpus_docs -> "list-documents")
            # runs before any unit's loop has called manifest(); without this it
            # got "unknown tool" and the coverage ledger reported "size unknown".
            # Guarded on an EMPTY table so a genuinely unknown name (table already
            # loaded) still fails fast without re-shelling. Best-effort: a failing
            # manifest load surfaces as a structured error, never an exception.
            try:
                self.manifest()
            except Exception as e:
                return ToolResult(ok=False, error=f"tool manifest load failed: {e}")
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


class MultiToolProvider:
    """Compose several ToolProviders into one. manifest() concatenates them;
    invoke() routes a tool name to the provider that owns it (first wins). The
    name->owner map is cached from the first manifest() call so a shelling
    provider is not re-invoked on every dispatch."""

    def __init__(self, providers: list):
        self._providers = list(providers)
        self._owner: dict | None = None

    def manifest(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        owner: dict = {}
        for p in self._providers:
            for s in p.manifest():
                specs.append(s)
                owner.setdefault(s.name, p)
        self._owner = owner
        return specs

    def invoke(self, name: str, args: dict) -> ToolResult:
        if self._owner is None:
            self.manifest()
        p = self._owner.get(name)
        if p is None:
            return ToolResult(ok=False, error=f"unknown tool: {name}")
        return p.invoke(name, args)


class LlmkbToolProvider:
    """Expose an llmkb knowledge base as read/write tools by shelling out to the
    `llmkb` CLI. Adapts llmkb's plain commands to the ToolProvider contract -
    llmkb itself stays unaware of madosho. The KB directory is fixed at
    construction; invoke() never raises into the loop."""

    def __init__(self, kb_dir: str, llmkb_argv: list[str] | None = None):
        self.kb_dir = kb_dir
        self.llmkb_argv = list(llmkb_argv or ["llmkb"])

    def manifest(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="kb_add_page",
                description=(
                    "Record a durable finding as a page in the knowledge base. "
                    "type is summary (one page per source), concept (synthesis "
                    "across sources), or entity (a person, org, system, or "
                    "product). Always set sources to the documents the finding "
                    "came from. Check kb_get_page first to avoid a duplicate title."),
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string",
                                 "enum": ["summary", "concept", "entity"]},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "body": {"type": "string"},
                    },
                    "required": ["type", "title", "description"],
                },
            ),
            ToolSpec(
                name="kb_get_page",
                description=("Read one knowledge-base page by title "
                             "(case-insensitive) before updating or to avoid duplicates."),
                parameters={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
        ]

    def invoke(self, name: str, args: dict) -> ToolResult:
        try:
            if name == "kb_add_page":
                return self._add_page(args)
            if name == "kb_get_page":
                return self._get_page(args)
            return ToolResult(ok=False, error=f"unknown tool: {name}")
        except Exception as exc:  # never raise into the loop
            return ToolResult(ok=False, error=f"{name} failed: {exc}")

    def _run(self, argv: list[str], stdin: str | None = None) -> ToolResult:
        proc = subprocess.run(self.llmkb_argv + argv, capture_output=True,
                              text=True, timeout=_TIMEOUT_S, input=stdin)
        if proc.returncode != 0:
            return ToolResult(ok=False, error=(proc.stderr or proc.stdout).strip())
        out = proc.stdout.strip()
        return ToolResult(ok=True, data=json.loads(out) if out else None)

    def _add_page(self, args: dict) -> ToolResult:
        argv = ["add-page", "--kb", self.kb_dir,
                "--type", str(args["type"]),
                "--title", str(args["title"]),
                "--description", str(args.get("description", ""))]
        tags = args.get("tags") or []
        if tags:
            argv += ["--tags", ",".join(str(t) for t in tags)]
        for src in (args.get("sources") or []):
            argv += ["--source", str(src)]
        argv += ["--body-file", "-", "--json"]
        return self._run(argv, stdin=str(args.get("body", "")))

    def _get_page(self, args: dict) -> ToolResult:
        return self._run(["get-page", str(args["title"]),
                          "--kb", self.kb_dir, "--json"])
