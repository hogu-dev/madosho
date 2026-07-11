"""madosho-cli - a thin command-line client over madosho's HTTP API.

Double duty: humans run it to inspect a running madosho; a research agent drives
it (every subcommand takes --json). HTTP only - no kernel/DB imports - so it is a
pure client that could be lifted out of this repo unchanged.

--json contract: stdout carries the result JSON or nothing; all errors print to
stderr and exit non-zero (what a tool driver keys off). Never error-JSON on stdout.
"""
from __future__ import annotations

import argparse
import sys

from . import commands, http


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON (what the agent uses)",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="madosho-cli",
        description="Command-line client over madosho's HTTP API.",
    )
    ap.add_argument(
        "--exclude-generated", action="store_true", dest="exclude_generated",
        help="hide alchemy-generated documents from search results",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-corpora", help="list available corpora")
    _add_json(p)
    p.set_defaults(func=commands.cmd_list_corpora)

    p = sub.add_parser("list-documents", help="list documents in a corpus")
    p.add_argument("corpus")
    _add_json(p)
    p.set_defaults(func=commands.cmd_list_documents)

    p = sub.add_parser("search", help="RAG retrieval over a corpus")
    p.add_argument("corpus")
    p.add_argument("query")
    p.add_argument("--top-k", type=int, default=8, dest="top_k",
                   help="max chunks to return (client-side truncation; default 8)")
    p.add_argument("--pipeline", default=None,
                   help="retrieve through this pipeline name (overrides each "
                        "document's effective pipeline)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_search)

    p = sub.add_parser("search-doc", help="RAG retrieval scoped to one document")
    p.add_argument("document_id", type=int)
    p.add_argument("query")
    p.add_argument("--top-k", type=int, default=8, dest="top_k",
                   help="max chunks to return (client-side truncation; default 8)")
    p.add_argument("--pipeline", default=None,
                   help="retrieve through this pipeline name (default: the "
                        "document's effective pipeline)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_search_doc)

    p = sub.add_parser("get-doc", help="full extracted text of one document (no RAG)")
    p.add_argument("document_id", type=int)
    p.add_argument("--pipeline", default=None,
                   help="pipeline name (default: the document's effective pipeline)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_get_doc)

    p = sub.add_parser("list-pipelines",
                       help="list pipelines on a document or across a corpus")
    p.add_argument("--corpus", default=None,
                   help="list pipelines across this corpus's documents")
    p.add_argument("--document-id", type=int, default=None, dest="document_id",
                   help="list pipelines built on this one document")
    _add_json(p)
    p.set_defaults(func=commands.cmd_list_pipelines)

    p = sub.add_parser("agent-tools",
                       help="emit the tool manifest a research agent consumes")
    _add_json(p)
    p.set_defaults(func=commands.cmd_agent_tools)

    # --- write subcommands ---

    p = sub.add_parser("create-corpus", help="create a new corpus")
    p.add_argument("name")
    _add_json(p)
    p.set_defaults(func=commands.cmd_create_corpus)

    p = sub.add_parser("upload-document", help="upload a document from a local path")
    p.add_argument("path", nargs="?", default=None,
                   help="local file path (content source)")
    p.add_argument("--filename", default=None,
                   help="override stored filename (default: basename of path)")
    p.add_argument("--corpus", default=None,
                   help="add document to this corpus")
    p.add_argument("--parser", default=None)
    p.add_argument("--chunker", default=None)
    p.add_argument("--embedder", default=None)
    p.add_argument("--options", default=None,
                   help="JSON object of extra parser/chunker options")
    p.add_argument("--no-wait", action="store_true", dest="no_wait",
                   help="return immediately after upload (do not poll for completion)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_upload_document)

    p = sub.add_parser("build-pipeline", help="build a new pipeline on a document")
    p.add_argument("document_id", type=int)
    p.add_argument("name")
    p.add_argument("--parser", default=None)
    p.add_argument("--chunker", default=None)
    p.add_argument("--embedder", default=None)
    p.add_argument("--options", default=None,
                   help="JSON object of extra options")
    p.add_argument("--config", default=None,
                   help="JSON full pipeline config (overrides individual slot flags)")
    p.add_argument("--no-wait", action="store_true", dest="no_wait",
                   help="return immediately after submit (do not poll for completion)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_build_pipeline)

    p = sub.add_parser("add-document-to-corpus",
                       help="associate an existing document with a corpus")
    p.add_argument("corpus")
    p.add_argument("document_id", type=int)
    _add_json(p)
    p.set_defaults(func=commands.cmd_add_document_to_corpus)

    p = sub.add_parser("document-status",
                       help="show the current status of a document")
    p.add_argument("document_id", type=int)
    _add_json(p)
    p.set_defaults(func=commands.cmd_document_status)

    # --- flat agent-facing goal tools (on the manifest; the nested `alchemy`
    # group below stays the richer human surface) ---

    p = sub.add_parser("list-goals", help="list alchemy goals")
    _add_json(p)
    p.set_defaults(func=commands.cmd_list_goals)

    p = sub.add_parser("goal-runs", help="list an alchemy goal's runs (newest first)")
    p.add_argument("goal", help="goal name or id")
    _add_json(p)
    p.set_defaults(func=commands.cmd_goal_runs)

    p = sub.add_parser("export-goal-run",
                       help="one run's draft + section summary as JSON (no files)")
    p.add_argument("goal", help="goal name or id")
    p.add_argument("--version", type=int, default=None,
                   help="run version (default: latest)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_export_goal_run)

    p = sub.add_parser("run-goal",
                       help="start a new run of an alchemy goal (returns immediately)")
    p.add_argument("goal", help="goal name or id")
    p.add_argument("max_llm_calls", type=int,
                   help="hard cap on LLM calls for this run")
    p.add_argument("--guidance", default=None,
                   help="steering note for this run")
    p.add_argument("--coverage", default=None,
                   choices=["search", "full", "exhaustive"])
    p.add_argument("--provider", default=None,
                   help="LLM provider (default: the server's default llm endpoint)")
    p.add_argument("--model", default=None,
                   help="LLM model name (default: the server's default llm endpoint)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_run_goal)

    p = sub.add_parser("list-runs",
                       help="list research or eval runs for a corpus")
    p.add_argument("corpus_id", type=int)
    p.add_argument("--type", choices=["research", "eval"], default="research",
                   help="run type to list (default: research)")
    p.add_argument("--active", action="store_true",
                   help="show only active runs (pending or running)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_list_runs)

    p = sub.add_parser("cancel-run",
                       help="cancel a research or eval run")
    p.add_argument("run_id", type=int)
    p.add_argument("--type", choices=["research", "eval"], default="research",
                   help="run type (default: research)")
    p.add_argument("--yes", action="store_true",
                   help="skip confirmation prompt")
    _add_json(p)
    p.set_defaults(func=commands.cmd_cancel_run)

    # --- alchemy (autonomous goals / living research) ---
    # Nested group (dest="subcommand"), CLI-only - not on the agent-tools
    # manifest, so it never reaches MCP/toolserver.

    alch = sub.add_parser("alchemy", help="autonomous goals (reports / living research)")
    alch_sub = alch.add_subparsers(dest="subcommand", required=True)

    p = alch_sub.add_parser("create", help="create a goal")
    p.add_argument("name")
    p.add_argument("--corpus", required=True, help="corpus name")
    p.add_argument("--type", dest="goal_type", default="living-research",
                   choices=["living-research", "report"])
    p.add_argument("--goal", default=None,
                   help="the goal statement (living-research)")
    p.add_argument("--spec", dest="spec_path", default=None,
                   help="markdown template file (report)")
    p.add_argument("--coverage", default="search",
                   choices=["search", "full", "exhaustive"])
    p.add_argument("--include-generated", action="store_true",
                   dest="include_generated",
                   help="let this goal's runs cite alchemy-generated documents")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_create)

    p = alch_sub.add_parser("run", help="start a run of a goal")
    p.add_argument("ref", help="goal name or id")
    p.add_argument("--provider", default=None,
                   help="LLM provider (with --model; omit both to use the "
                        "server's default LLM endpoint)")
    p.add_argument("--model", default=None,
                   help="LLM model (with --provider; omit both to use the "
                        "server's default LLM endpoint)")
    p.add_argument("--coverage", default=None,
                   choices=["search", "full", "exhaustive"])
    p.add_argument("--fresh-coverage", action="store_true",
                   help="re-consult the corpus from scratch instead of "
                        "inheriting coverage from the run this revises")
    p.add_argument("--guidance", default=None)
    p.add_argument("--based-on", dest="based_on", type=int, default=None,
                   help="version to revise (default: latest with a draft)")
    p.add_argument("--max-llm-calls", dest="max_llm_calls", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=1,
                   help="parallel work units per run (1-8, default 1)")
    p.add_argument("--no-wait", dest="no_wait", action="store_true")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_run)

    p = alch_sub.add_parser("status", help="show a run's status")
    p.add_argument("ref")
    p.add_argument("--run", type=int, default=None, help="version (default: latest)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_status)

    p = alch_sub.add_parser("export",
                            help="write a run's draft to a markdown or JSON file")
    p.add_argument("ref")
    p.add_argument("--run", type=int, default=None, help="version (default: latest)")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--format", dest="format", default="md",
                   choices=["md", "json"],
                   help="md = the rendered markdown draft; "
                        "json = structured section results")
    p.set_defaults(func=commands.cmd_alchemy_export)

    p = alch_sub.add_parser("finalize", help="mark a version final")
    p.add_argument("ref")
    p.add_argument("--run", type=int, required=True, help="version to finalize")
    p.add_argument("--ingest", action="store_true",
                   help="also ingest the draft as a generated document")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_finalize)

    p = alch_sub.add_parser(
        "ingest", help="ingest a run's draft as a generated document")
    p.add_argument("ref")
    p.add_argument("--run", type=int, default=None,
                   help="version (default: latest)")
    p.add_argument("--corpus", default=None,
                   help="target corpus (default: the goal's corpus)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_ingest)

    p = alch_sub.add_parser("list", help="list goals")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_list)

    p = alch_sub.add_parser("runs", help="list a goal's runs")
    p.add_argument("ref")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_runs)

    p = alch_sub.add_parser("artifacts", help="list a run's stage artifacts")
    p.add_argument("ref")
    p.add_argument("--run", type=int, default=None, help="version (default: latest)")
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_artifacts)

    p = alch_sub.add_parser("cancel", help="cancel a run by id")
    p.add_argument("run_id", type=int)
    _add_json(p)
    p.set_defaults(func=commands.cmd_alchemy_cancel)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except http.CliError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
