"""Subcommand handlers for the madosho CLI.

Each prints human-readable output by default and machine-readable JSON under
--json. A research agent always passes --json. The HTTP orchestration lives in
core.py (shared with the OpenAPI tool server); these handlers only format.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from . import core, http
from .manifest import build_manifest


def _emit(data: Any) -> None:
    """Print a value as indented JSON (the --json path)."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _emit_or_print(args: argparse.Namespace, data: Any, human) -> None:
    """Dispatch to _emit under --json, else print human's rendering of data.

    The rest of commands.py inlines this `if args.json: _emit(...) else: ...`
    check by hand; alchemy's handlers share so much of this shape (a single
    dict, one human-readable line or table) that a helper pays for itself.
    """
    if getattr(args, "json", False):
        _emit(data)
    else:
        print(human(data))


def cmd_list_corpora(args: argparse.Namespace) -> int:
    data = core.list_corpora()
    if args.json:
        _emit(data)
    else:
        corpora = data["corpora"]
        if not corpora:
            print("(no corpora)")
        for c in corpora:
            print(f"{c['id']:>4}  {c['name']}")
    return 0


def cmd_list_documents(args: argparse.Namespace) -> int:
    data = core.list_documents(args.corpus)
    if args.json:
        _emit(data)
    else:
        docs = data["documents"]
        if not docs:
            print("(no documents)")
        for d in docs:
            print(f"{d['id']:>4}  {d['status']:<10}  {d['filename']}")
    return 0


def _print_hits(hits: list) -> None:
    print(f"retrieved {len(hits)} chunks:")
    for i, h in enumerate(hits, 1):
        snippet = " ".join((h.get("text") or "").split())[:100]
        print(f"  [{i}] {h.get('citation')}  (score {h.get('score', 0):.3f})  {snippet}")


def cmd_search(args: argparse.Namespace) -> int:
    data = core.search(args.corpus, args.query, top_k=args.top_k,
                       pipeline=args.pipeline)
    if args.json:
        _emit(data)
    else:
        _print_hits(data["hits"])
    return 0


def cmd_search_doc(args: argparse.Namespace) -> int:
    data = core.search_document(args.document_id, args.query, top_k=args.top_k,
                                pipeline=args.pipeline)
    if args.json:
        _emit(data)
    else:
        _print_hits(data["hits"])
    return 0


def cmd_get_doc(args: argparse.Namespace) -> int:
    data = core.get_doc(args.document_id, args.pipeline)
    if args.json:
        _emit(data)
    else:
        print(
            f"# document {data['document_id']} via pipeline "
            f"'{data['pipeline']}' ({data['char_count']} chars)\n"
        )
        print(data["text"])
    return 0


def cmd_list_pipelines(args: argparse.Namespace) -> int:
    data = core.list_pipelines(corpus=args.corpus, document_id=args.document_id)
    if args.json:
        _emit(data)
    else:
        pls = data["pipelines"]
        if not pls:
            print("(no pipelines)")
        for p in pls:
            rating = p.get("rating")
            rating_s = f"{rating:.2f}" if isinstance(rating, (int, float)) else "  -  "
            mark = "*" if p.get("effective") else " "
            print(f"{mark} {rating_s:>6}  {p.get('status', ''):<10}  {p['name']}")
    return 0


def cmd_agent_tools(args: argparse.Namespace) -> int:
    manifest = build_manifest()
    if args.json:
        _emit(manifest)
    else:
        for t in manifest["tools"]:
            print(f"{t['name']:<16} {t['description']}")
    return 0


# ---------------------------------------------------------------------------
# Write subcommands
# ---------------------------------------------------------------------------

def _parse_json_arg(value: str | None, flag: str) -> Any:
    """Parse a JSON flag value; raise CliError on bad JSON."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise http.CliError(f"--{flag}: invalid JSON: {e}") from e


def _on_event_printer(event: dict) -> None:
    """Progress callback: print phase/log lines from a status event."""
    status = event.get("status", "")
    progress = event.get("progress") or {}
    phase = progress.get("phase", "")
    log = progress.get("log", "")
    if log:
        print(f"  [{status}] {log}")
    elif phase:
        print(f"  [{status}] {phase}")
    else:
        print(f"  [{status}]")


def cmd_create_corpus(args: argparse.Namespace) -> int:
    data = core.create_corpus(args.name)
    if args.json:
        _emit(data)
    else:
        print(f"created corpus {data['id']}  {data['name']}")
    return 0


def cmd_upload_document(args: argparse.Namespace) -> int:
    options = _parse_json_arg(args.options, "options")
    data = core.upload_document(
        path=args.path,
        filename=args.filename,
        corpus=args.corpus,
        parser=args.parser,
        chunker=args.chunker,
        embedder=args.embedder,
        options=options,
    )
    doc_id = data["id"]
    if args.no_wait:
        if args.json:
            _emit(data)
        else:
            print(f"document {doc_id}  {data.get('status', '')}")
        return 0
    # Block until indexed
    final = core.wait_for_document(doc_id, on_event=_on_event_printer)
    failed = final.get("status") == "failed"
    if args.json:
        _emit(final)
    else:
        print(f"document {final['id']}  {final['status']}")
    return 1 if failed else 0


def cmd_build_pipeline(args: argparse.Namespace) -> int:
    options = _parse_json_arg(args.options, "options")
    config = _parse_json_arg(args.config, "config")
    data = core.build_pipeline(
        args.document_id,
        args.name,
        parser=args.parser,
        chunker=args.chunker,
        embedder=args.embedder,
        options=options,
        config=config,
    )
    pipeline_id = data["id"]
    if args.no_wait:
        if args.json:
            _emit(data)
        else:
            print(f"pipeline {pipeline_id}  {data.get('status', '')}")
        return 0
    # Block until pipeline reaches terminal state
    final = core.wait_for_pipeline(args.document_id, pipeline_id,
                                   on_event=_on_event_printer)
    # Find the pipeline in the returned status dict
    pipelines = final.get("pipelines", [])
    pl = next((p for p in pipelines if p["id"] == pipeline_id), None)
    failed = (pl is not None and pl.get("status") == "failed")
    if args.json:
        _emit(final)
    else:
        if pl is not None:
            status = pl.get("status", "")
            err = pl.get("error", "")
            print(f"pipeline {pipeline_id}  {status}" + (f"  error: {err}" if err else ""))
        else:
            print(f"pipeline {pipeline_id}  (status unknown)")
    return 1 if failed else 0


def cmd_add_document_to_corpus(args: argparse.Namespace) -> int:
    data = core.add_document_to_corpus(args.corpus, args.document_id)
    if args.json:
        _emit(data)
    else:
        print(f"document {args.document_id} added to corpus {args.corpus!r}")
    return 0


def cmd_document_status(args: argparse.Namespace) -> int:
    data = core.document_status(args.document_id)
    if args.json:
        _emit(data)
    else:
        status = data.get("status", "")
        err = data.get("error", "")
        print(f"document {args.document_id}  {status}" + (f"  error: {err}" if err else ""))
        pipelines = data.get("pipelines", [])
        for pl in pipelines:
            mark = "*" if pl.get("effective") else " "
            print(f"  {mark} pipeline {pl.get('id')}  {pl.get('status', ''):<10}  {pl.get('name', '')}")
    return 0


def cmd_list_runs(args: argparse.Namespace) -> int:
    data = core.list_runs(args.corpus_id, args.type, args.active)
    if args.json:
        _emit(data)
    else:
        runs = data["runs"]
        if not runs:
            print("(no runs)")
        for r in runs:
            print(f"{r['id']:>4}  {r['status']:<10}  {args.type}")
    return 0


# ---------------------------------------------------------------------------
# alchemy subcommands (autonomous goals / living research; CLI-only, not on
# the manifest - see manifest.py's docstring for why)
# ---------------------------------------------------------------------------

def cmd_alchemy_create(args: argparse.Namespace) -> int:
    data = core.alchemy_create(args.name, args.corpus, args.goal,
                               coverage=args.coverage)
    _emit_or_print(args, data, lambda d: f"created goal {d['name']} (id {d['id']})")
    return 0


def cmd_alchemy_run(args: argparse.Namespace) -> int:
    data = core.alchemy_run(args.ref, args.provider, args.model,
                            coverage=args.coverage, guidance=args.guidance,
                            based_on_version=args.based_on,
                            max_llm_calls=args.max_llm_calls)
    version = data["version"]
    if args.no_wait:
        _emit_or_print(args, data, lambda d: f"started {args.ref} v{d['version']} (pending)")
        return 0
    final = core.wait_for_alchemy_run(args.ref, version, on_event=_on_event_printer)
    _emit_or_print(args, final,
                   lambda d: f"{args.ref} v{d['version']}: {d['status']} "
                             f"({(d.get('usage') or {}).get('llm_calls', 0)} llm calls)")
    return 1 if final.get("status") == "failed" else 0


def cmd_alchemy_status(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    data = core.alchemy_get_run(args.ref, version)
    _emit_or_print(args, data,
                   lambda d: f"{args.ref} v{d['version']}: {d['status']} "
                             f"phase={(d.get('progress') or {}).get('phase')}")
    return 0


def cmd_alchemy_export(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    run = core.alchemy_get_run(args.ref, version)
    md = run.get("draft_markdown") or ""
    target = args.output or f"{args.ref}-v{version}.md"
    with open(target, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {target} ({len(md)} chars)")
    return 0


def cmd_alchemy_finalize(args: argparse.Namespace) -> int:
    data = core.alchemy_finalize(args.ref, args.run)
    _emit_or_print(args, data, lambda d: f"finalized {args.ref} v{d['version']}")
    return 0


def cmd_alchemy_list(args: argparse.Namespace) -> int:
    data = core.alchemy_list_goals()
    _emit_or_print(args, data,
                   lambda rows: "\n".join(f"{g['id']}\t{g['name']}\t"
                                          f"corpus {g['corpus_id']}" for g in rows)
                                or "no goals")
    return 0


def cmd_alchemy_runs(args: argparse.Namespace) -> int:
    data = core.alchemy_list_runs(args.ref)
    _emit_or_print(args, data,
                   lambda rows: "\n".join(f"v{r['version']}\t{r['status']}\t"
                                          f"{'FINAL' if r.get('is_final') else ''}"
                                          for r in rows) or "no runs")
    return 0


def cmd_alchemy_cancel(args: argparse.Namespace) -> int:
    data = core.alchemy_cancel(args.run_id)
    _emit_or_print(args, data, lambda d: f"run {args.run_id}: {d['status']}")
    return 0


def cmd_cancel_run(args: argparse.Namespace) -> int:
    if not args.yes:
        try:
            reply = input(f"Cancel {args.type} run {args.run_id}? [y/N] ")
        except EOFError:
            print("aborted")
            return 0
        if reply.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 0
    data = core.cancel_run(args.run_id, args.type)
    if args.json:
        _emit(data)
    else:
        print(f"status: {data.get('status', '')}")
    return 0
