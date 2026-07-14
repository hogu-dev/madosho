"""Subcommand handlers for the madosho CLI.

Each prints human-readable output by default and machine-readable JSON under
--json. A research agent always passes --json. The HTTP orchestration lives in
core.py (shared with the OpenAPI tool server); these handlers only format.
"""
from __future__ import annotations

import argparse
import json
import sys
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
            # origin_label is carried verbatim from the API row (the formula
            # lives once, in provenance.origin_label) -- source rows have "".
            label = d.get("origin_label") or ""
            suffix = f"  {label}" if label else ""
            print(f"{d['id']:>4}  {d['status']:<10}  {d['filename']}{suffix}")
    return 0


def _print_hits(hits: list) -> None:
    print(f"retrieved {len(hits)} chunks:")
    for i, h in enumerate(hits, 1):
        snippet = " ".join((h.get("text") or "").split())[:100]
        print(f"  [{i}] {h.get('citation')}  (score {h.get('score', 0):.3f})  {snippet}")


def cmd_search(args: argparse.Namespace) -> int:
    data = core.search(args.corpus, args.query, top_k=args.top_k,
                       pipeline=args.pipeline,
                       include_generated=not getattr(args, "exclude_generated", False))
    if args.json:
        _emit(data)
    else:
        _print_hits(data["hits"])
    return 0


def cmd_search_doc(args: argparse.Namespace) -> int:
    data = core.search_document(args.document_id, args.query, top_k=args.top_k,
                                pipeline=args.pipeline,
                                include_generated=not getattr(args, "exclude_generated", False))
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


def cmd_create_kb(args: argparse.Namespace) -> int:
    data = core.create_kb(args.corpus, args.name)
    if args.json:
        _emit(data)
    else:
        print(f"created KB {data['name']} (id {data['id']})")
    return 0


def cmd_list_kbs(args: argparse.Namespace) -> int:
    data = core.list_kbs()
    if args.json:
        _emit(data)
    else:
        if not data:
            print("(no knowledge bases)")
        for k in data:
            print(f"{k['id']:>4}  {k['corpus_name']}  {k['name']}")
    return 0


def cmd_get_kb_page(args: argparse.Namespace) -> int:
    data = core.get_kb_page(args.kb_id, args.slug)
    if args.json:
        _emit(data)
    else:
        print(data.get("body", ""))
    return 0


def cmd_add_kb_page(args: argparse.Namespace) -> int:
    tags = args.tags.split(",") if args.tags else []
    sources = args.source or []
    body = sys.stdin.read() if args.body_file == "-" else (args.body or "")
    data = core.add_kb_page(args.kb_id, type=args.type, title=args.title,
                            description=args.description or "", tags=tags,
                            sources=sources, body=body)
    if args.json:
        _emit(data)
    else:
        print(f"added page {data['slug']}")
    return 0


def cmd_edit_kb_page(args: argparse.Namespace) -> int:
    body = None
    if args.body_file == "-":
        body = sys.stdin.read()
    elif args.body is not None:
        body = args.body
    data = core.edit_kb_page(args.kb_id, args.slug,
                             description=args.description, body=body)
    if args.json:
        _emit(data)
    else:
        print(f"edited page {data['slug']}")
    return 0


def cmd_search_kb(args: argparse.Namespace) -> int:
    data = core.search_kb(args.kb_id, args.query)
    if args.json:
        _emit(data)
    else:
        if not data:
            print("(no results)")
        for h in data:
            print(f"{h['slug']}\t{h['title']}")
    return 0


def cmd_import_kb(args: argparse.Namespace) -> int:
    import base64
    from . import kb_pack
    try:
        filename, content = kb_pack.pack_kb(args.path)
    except kb_pack.KbPackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    result = core.upload_document(content_b64=b64, filename=filename, corpus=args.corpus)
    doc_id = result.get("id")
    if args.no_wait or doc_id is None:
        final = result
    else:
        final = core.wait_for_document(doc_id, on_event=_on_event_printer)
    if args.json:
        _emit(final)
    else:
        print(f"imported KB {args.path} as document {doc_id} ({final.get('status')})")
    return 1 if final.get("status") == "failed" else 0


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
# flat agent-facing goal tools (ON the manifest, unlike the nested `alchemy`
# group below, which stays the richer human surface)
# ---------------------------------------------------------------------------

def cmd_list_goals(args: argparse.Namespace) -> int:
    data = core.alchemy_list_goals()
    _emit_or_print(args, data,
                   lambda rows: "\n".join(f"{g['id']}\t{g['name']}\t"
                                          f"corpus {g['corpus_id']}" for g in rows)
                                or "no goals")
    return 0


def cmd_goal_runs(args: argparse.Namespace) -> int:
    data = core.alchemy_list_runs(args.goal)
    _emit_or_print(args, data,
                   lambda rows: "\n".join(f"v{r['version']}\t{r['status']}\t"
                                          f"{'FINAL' if r.get('is_final') else ''}"
                                          for r in rows) or "no runs")
    return 0


def cmd_export_goal_run(args: argparse.Namespace) -> int:
    data = core.alchemy_export_run(args.goal, version=args.version)
    _emit_or_print(args, data,
                   lambda d: f"{d['goal']} v{d['version']}: {d['status']} "
                             f"({len(d['draft_markdown'])} chars, "
                             f"{d['citations']} citations)")
    return 0


def cmd_run_goal(args: argparse.Namespace) -> int:
    # No waiting here (unlike cmd_alchemy_run): agents poll goal-runs instead.
    # Both provider and model may be None; they pass through so the server-side
    # default llm-endpoint fallback owns the substitution. But a LONE one is a
    # typo, not a request for the default - fail fast locally (same guard and
    # message as cmd_alchemy_run) instead of eating a 400 network round-trip.
    if (args.provider is None) != (args.model is None):
        raise http.CliError(
            "--provider and --model must be given together "
            "(omit both to use the server's default LLM endpoint)")
    data = core.alchemy_run(args.goal, args.provider, args.model,
                            coverage=args.coverage, guidance=args.guidance,
                            max_llm_calls=args.max_llm_calls,
                            reasoning_effort=args.reasoning_effort)
    _emit_or_print(args, data,
                   lambda d: f"started {args.goal} v{d['version']} "
                             f"({d['status']}); poll goal-runs")
    return 0


# ---------------------------------------------------------------------------
# alchemy subcommands (autonomous goals / living research; CLI-only, not on
# the manifest - see manifest.py's docstring for why)
# ---------------------------------------------------------------------------

def cmd_alchemy_create(args: argparse.Namespace) -> int:
    if args.goal_type == "report":
        # reject --goal here rather than silently dropping it: a report's goal
        # statement comes from the template's title+preamble, so a --goal flag
        # signals the user misunderstands which knob does what
        if args.goal:
            raise http.CliError(
                "--goal is not used with --type report; the report's goal "
                "statement is the template's title and intro prose")
        if not args.spec_path:
            raise http.CliError("--spec TEMPLATE.md is required for --type report")
        try:
            with open(args.spec_path, encoding="utf-8") as f:
                template = f.read()
        except OSError as e:
            raise http.CliError(f"cannot read spec file: {e}")
        spec = {"template": template}
    else:
        # --spec is a report-only flag; flag it instead of ignoring it
        if args.spec_path:
            raise http.CliError(
                "--spec is only for --type report; living-research takes --goal")
        if not args.goal:
            raise http.CliError("--goal is required for --type living-research")
        spec = {"goal": args.goal}
    data = core.alchemy_create(args.name, args.corpus, spec,
                               goal_type=args.goal_type,
                               coverage=args.coverage,
                               include_generated=args.include_generated)
    _emit_or_print(args, data, lambda d: f"created goal {d['name']} (id {d['id']})")
    return 0


def cmd_alchemy_run(args: argparse.Namespace) -> int:
    # both-or-neither: a lone --provider (or --model) is a typo, not a request
    # for the server's default endpoint - fail fast here instead of burning a
    # 400 round-trip (same reject-don't-ignore stance as cmd_alchemy_create)
    if (args.provider is None) != (args.model is None):
        raise http.CliError(
            "--provider and --model must be given together "
            "(omit both to use the server's default LLM endpoint)")
    data = core.alchemy_run(args.ref, args.provider, args.model,
                            coverage=args.coverage, guidance=args.guidance,
                            based_on_version=args.based_on,
                            max_llm_calls=args.max_llm_calls,
                            fresh_coverage=args.fresh_coverage,
                            concurrency=args.concurrency,
                            reasoning_effort=args.reasoning_effort)
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

    def _fmt(d):
        lines = [f"{args.ref} v{d['version']}: {d['status']} "
                 f"phase={(d.get('progress') or {}).get('phase')}"]
        for s in d.get("sections") or []:
            conf = s.get("confidence") or {}
            line = (f"  {(s.get('title') or s.get('key') or ''):<28} "
                    f"{conf.get('level', '-'):<7} "
                    f"({conf.get('distinct_docs', 0)} docs, "
                    f"{conf.get('citations', 0)} cites)")
            if not s.get("filled"):
                line += f"  not filled: {s.get('note') or '-'}"
            lines.append(line)
        summary = (d.get("ledger") or {}).get("summary")
        if summary:
            lines.append(f"  coverage: {summary}")
        counts = d.get("artifact_counts") or {}
        if counts:
            # sorted for a stable line: "artifacts: 2 digest, 1 handoff"
            parts = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
            lines.append(f"  artifacts: {parts}")
        return "\n".join(lines)

    _emit_or_print(args, data, _fmt)
    return 0


def _draft_title(run: dict) -> str:
    """The report H1, recovered from the persisted draft's first '# ' line.
    The run JSON does not carry the compiled title on its own, but the report
    renderer always emits it as the leading '# ' heading, so the draft is the
    faithful source. Empty when there is no such heading (living-research)."""
    for line in (run.get("draft_markdown") or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _run_to_json(run: dict) -> dict:
    """Structured JSON VIEW of a report run's persisted section results.

    A faithful, mechanical echo (no LLM, no synthesis) of each section's
    content, filled flag, confidence blob, and shortfall note, so a partial
    export is exactly as honest as the markdown one. Built here in the CLI -
    NOT imported from alchemy.render - because madosho_cli is a pure HTTP
    client that must not drag the engine (alchemy -> research_agent) in on the
    export path; the run GET already carries `sections`+`citations`, so this
    is a local reshape of data the client holds, not a re-derivation. The
    `citations` key is OMITTED when the run has none, so its presence is
    meaningful."""
    doc = {
        "title": _draft_title(run),
        "sections": [
            {"key": s.get("key", ""), "title": s.get("title", ""),
             "content": s.get("content", ""),
             "filled": bool(s.get("filled", False)),
             "confidence": s.get("confidence") or {},
             "note": s.get("note", "")}
            for s in (run.get("sections") or [])
        ],
    }
    if run.get("citations") is not None:
        doc["citations"] = run["citations"]
    return doc


def cmd_alchemy_export(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    run = core.alchemy_get_run(args.ref, version)
    if args.format == "json":
        doc = _run_to_json(run)
        target = args.output or f"{args.ref}-v{version}.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=True)
        print(f"wrote {target} ({len(doc['sections'])} sections)")
        return 0
    md = run.get("draft_markdown") or ""
    target = args.output or f"{args.ref}-v{version}.md"
    with open(target, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {target} ({len(md)} chars)")
    return 0


def cmd_alchemy_finalize(args: argparse.Namespace) -> int:
    data = core.alchemy_finalize(args.ref, args.run, ingest=args.ingest)
    _emit_or_print(args, data, lambda d: f"finalized {args.ref} v{d['version']}"
                                         + (" (ingested)" if args.ingest else ""))
    return 0


def cmd_alchemy_ingest(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    data = core.alchemy_ingest(args.ref, version, corpus=args.corpus)
    _emit_or_print(
        args, data,
        lambda d: f"ingested {args.ref} v{version} -> document {d['id']} "
                  f"({d.get('filename', '')})")
    return 0


def cmd_alchemy_to_kb(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    data = core.alchemy_save_to_kb(
        args.ref, version, kb_id=args.kb_id, kb_name=args.kb_name,
        corpus=args.corpus, title=args.title, type=args.type)
    _emit_or_print(
        args, data,
        lambda d: f"saved {args.ref} v{version} -> KB {d['kb_id']} "
                  f"page '{d['slug']}' ({d['action']})")
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


def _artifact_summary(kind, payload):
    """One-line, kind-aware payload gloss for the human view. Cheap: reads a
    couple of keys, never dumps the whole payload (use --json for that)."""
    payload = payload or {}
    if kind == "digest":
        return (f"{payload.get('filename', '?')} "
                f"({len(payload.get('text') or '')} chars)")
    if kind == "handoff":
        docs = payload.get("docs_covered") or []
        return (f"attempt {payload.get('attempt', '?')}, "
                f"{len(docs)} docs, {payload.get('partial_chars', 0)} chars")
    return ""


def cmd_alchemy_artifacts(args: argparse.Namespace) -> int:
    version = args.run or core.alchemy_latest_version(args.ref)
    if version is None:
        raise http.CliError(f"no runs for goal {args.ref}")
    data = core.alchemy_list_artifacts(args.ref, version)

    def _fmt(rows):
        if not rows:
            return "no artifacts"
        return "\n".join(
            f"{(a.get('kind') or '-'):<8} {(a.get('key') or ''):<24} "
            f"{_artifact_summary(a.get('kind'), a.get('payload'))}"
            for a in rows)

    _emit_or_print(args, data, _fmt)
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
