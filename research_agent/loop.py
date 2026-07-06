"""The retrieve-reason-retrieve loop.

A synchronous OpenAI-format tool-calling loop. The model is given the tools from
the provider's manifest; it calls them; results feed back; it ends by writing a
final report or by hitting the round cap (then we force one synthesis turn). The
loop is bounded by budget.max_rounds and budget.max_context_chars - it never feeds
more source text than the budget, and never hangs on a bad tool (the provider
returns structured errors, not exceptions).

WHY gather citations mechanically (not ask the model to emit structured ones):
every search hit and whole-document read already carries madosho's document/
pipeline/position attribution. Collecting and de-duplicating those is robust and
auditable - the report body is the model's prose, the citations are ground truth
about what it actually retrieved.
"""
from __future__ import annotations

import json
from typing import Callable

from .llm import LlmClient
from .tools import ToolProvider, render_manifest, to_openai_tools
from .types import Citation, Report, RunBudget


def _citations_from(name: str, data) -> list[Citation]:
    out: list[Citation] = []
    if not isinstance(data, dict):
        return out
    if name in ("search", "search-doc"):   # same hit shape, corpus- vs doc-scoped
        for h in data.get("hits", []):
            out.append(Citation(
                document_id=h.get("document_id"), pipeline_id=h.get("pipeline_id"),
                pipeline=h.get("pipeline"), position=h.get("position"),
                citation=h.get("citation") or "", source=h.get("source"),
                score=h.get("score"), quote=(h.get("text") or "")[:500]))
    elif name == "get-doc":
        out.append(Citation(
            document_id=data.get("document_id"), pipeline_id=data.get("pipeline_id"),
            pipeline=data.get("pipeline"), position=None,
            citation=f"document {data.get('document_id')} (whole text)",
            source=None, score=None, quote=(data.get("text") or "")[:500]))
    return out


def _dedupe(cits: list[Citation]) -> list[Citation]:
    seen: set = set()
    seen_quotes: set = set()   # (document_id, quote): the SAME passage cited via two
                               # tools - e.g. a `search` hit and then a whole-text
                               # `get-doc` of the same document - arrives with
                               # different (doc, pipeline, position) keys but identical
                               # text. Keep the first (better-attributed) one.
    out: list[Citation] = []
    for c in cits:
        key = (c.document_id, c.pipeline_id, c.position)
        if key == (None, None, None):
            out.append(c)   # never collapse anonymous citations
            continue
        if key in seen:
            continue
        if c.document_id is not None and c.quote:
            qkey = (c.document_id, c.quote)
            if qkey in seen_quotes:
                continue
            seen_quotes.add(qkey)
        seen.add(key)
        out.append(c)
    return out


def run_loop(prompt: str, autonomous_md: str, tools: ToolProvider,
             llm: LlmClient, budget: RunBudget, *,
             should_cancel: Callable[[], bool] | None = None) -> Report:
    specs = tools.manifest()
    tool_schemas = to_openai_tools(specs)
    system = autonomous_md + "\n\n## Tools available\n" + render_manifest(specs)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    run_log: list[dict] = []
    citations: list[Citation] = []
    chars_used = 0
    final_text = ""
    stop_reason = "final"
    got_final = False

    for round_no in range(1, budget.max_rounds + 1):
        if should_cancel is not None and should_cancel():
            return Report(markdown=final_text, citations=_dedupe(citations),
                          run_log=run_log, stop_reason="cancelled")
        turn = llm.complete(messages, tool_schemas)
        run_log.append({"round": round_no, "kind": "llm",
                        "has_tool_calls": bool(turn.tool_calls),
                        "text_chars": len(turn.text or "")})
        if not turn.tool_calls:
            if turn.text:
                final_text = turn.text
                stop_reason = "final"
                got_final = True
                break
            elif round_no == 1:
                # genuinely produced nothing on the first turn
                stop_reason = "no_tools_used"
                got_final = True
                break
            else:
                # degenerate empty turn on round 2+: fall through to forced synthesis
                break

        messages.append({
            "role": "assistant",
            "content": turn.text or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in turn.tool_calls
            ],
        })
        for tc in turn.tool_calls:
            result = tools.invoke(tc.name, tc.arguments)
            if result.ok:
                citations.extend(_citations_from(tc.name, result.data))
            note = None
            remaining = budget.max_context_chars - chars_used
            if not result.ok:
                payload = json.dumps({"error": result.error})
            elif remaining <= 0:
                payload = json.dumps(
                    {"note": "context budget reached; stop searching and write the report"})
                note = "context budget reached"
            else:
                payload = json.dumps(result.data, ensure_ascii=False)
                if len(payload) > remaining:
                    payload = payload[:remaining]
                    note = "truncated to fit context budget"
            chars_used += len(payload)
            run_log.append({"round": round_no, "kind": "tool_call", "name": tc.name,
                            "args": tc.arguments, "ok": result.ok, "error": result.error,
                            "chars": len(payload), "note": note})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})

    if not got_final:
        messages.append({"role": "user", "content":
                         "You have reached the research round limit. Write the final "
                         "report now from the evidence you have gathered."})
        turn = llm.complete(messages, [])
        run_log.append({"round": budget.max_rounds + 1, "kind": "llm",
                        "has_tool_calls": False, "text_chars": len(turn.text or "")})
        final_text = turn.text or ""
        stop_reason = "round_cap"

    return Report(markdown=final_text, citations=_dedupe(citations),
                  run_log=run_log, stop_reason=stop_reason)
