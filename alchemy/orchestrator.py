"""The orchestrator: compile the spec, farm out bounded work units, meter
the spend, assemble the draft.

living-research (stage A) stays a single unit: compose one prompt, run one
bounded research loop, return its report verbatim. report (stage B) runs ONE
unit per compiled section - context-full is the normal case, so each section
gets a fresh bounded loop instead of one long conversation; the orchestrator
holds only compact results, never raw source text.

max_llm_calls is a per-RUN cap shared across units via a single CountingLlm.
Each unit's quota is greedy-with-a-floor: max(2, fair share of the REMAINING
allowance). WHY not strict fair share: with a small cap, fair share can be
below the 2-call minimum every unit needs (one working round + the forced
synthesis) even though the allowance could fill SOME sections - and a
partial report beats an empty one. The loop spends one call per round plus
one forced synthesis, so quota-1 rounds keeps a unit within quota. When
fewer than 2 calls remain, the remaining sections are skipped honestly and
the run stops with stop reason "call_cap", a draft, and per-section
shortfall notes. CountingLlm's own cap stays the backstop for the day the
loop's call pattern changes.

Partial survival is a hard guarantee: sections that already landed survive
BOTH a call-cap trip (backstop or floor) AND a unit crash (a section's
research loop raising). A crash sets the run's stop reason to "failed" and
halts the remaining sections, but never discards what earlier units produced.
On a rerun, a section that ends unfilled for ANY reason (cap, cancel, crash,
empty) falls back to the prior run's content for that section if it had any -
so a rerun can only improve a report, never regress a section it once filled.

Stage C adds coverage ENFORCEMENT behind the same run_goal signature, in two
phases per mode. `full`: after the section units run (or the one living-research
unit), every still-unconsulted doc gets a system-side forced search-doc pass
(zero LLM calls - the model cannot dodge a doc by not searching it), and weak
sections that received forced evidence get one metered revision call each
(_forced_pass). `exhaustive` mines every doc BEFORE the units run instead
(Task 6). Neither phase changes run_goal's signature or GoalRunResult's shape
- WHY the server adapter and CLI never change when the engine deepens.
"""
from __future__ import annotations

from dataclasses import replace

import research_agent
from research_agent.types import Citation

from .compile import compile_spec
from .confidence import blend_confidence, split_grade_marker
from .ledger import (COVERAGE_MODES, CoverageLedger, citations_from_hits,
                     list_corpus_docs)
from .llm import CallCapExceeded, CountingLlm
from .prompts import (MINING_MD, compose_continuation_prompt,
                      compose_coverage_query, compose_forced_revision_prompt,
                      compose_mining_prompt, compose_prompt,
                      compose_section_prompt, load_report_md)
from .render import render_report
from .types import GoalRunResult, SectionResult

_MIN_UNIT_CALLS = 2   # one working round + the forced synthesis
_MAX_HANDOFFS = 2   # continuations spawned per unit that runs out of round
                    # budget before finishing; small on purpose - each costs a
                    # whole unit's worth of calls, and the point is to rescue a
                    # truncated draft, not to grind indefinitely
_FORCED_TOP_K = 5          # chunks pulled per untouched doc in a forced pass
_WEAK_SECTION_CAP = 3      # revision targets per forced pass; more dilutes
                           # the query and multiplies revision calls
_EVIDENCE_CHAR_CAP = 8000  # evidence text per revision prompt; a one-turn
                           # revision must fit small models comfortably
_DIGEST_CHAR_CAP = 1500       # per-doc digest cap: digests must stay compact
                              # enough that ALL of them fit a section prompt
_DIGEST_BLOCK_CAP = 24_000    # total digest block injected per prompt


def _weak_sections(results: list, cap: int = _WEAK_SECTION_CAP) -> list:
    """The forced pass's revision targets: unfilled sections first (template
    order), then filled ones from lowest confidence up. WHY a cap: the forced
    QUERY quotes these sections and each one costs a revision call - past a
    few, the pass stops being a targeted repair and becomes a rewrite."""
    unfilled = [r for r in results if not r.filled]
    order = {lvl: i for i, lvl in enumerate(("low", "medium", "high"))}
    filled = sorted((r for r in results if r.filled),
                    key=lambda r: order.get((r.confidence or {}).get("level"), 1))
    return (unfilled + filled)[:cap]


def _forced_pass(ledger, weak: list, *, goal: str, tools, counting,
                 max_llm_calls, should_cancel, on_progress, own_cits=None):
    """Enforce `full` coverage: system-side search-doc over every untouched
    doc (zero LLM calls - the model cannot skip docs by not searching), then
    one metered revision call per weak section that evidence came back for.

    Returns (new_citations, halted_reason_or_None). Mutates the ledger and
    the weak SectionResults in place. Never raises: retrieval failures land
    in ledger.failures, a call-cap trip lands in ledger.shortfall - honest
    shortfall, not a dead run."""
    new_citations: list = []
    evidence: list[str] = []
    untouched = ledger.unconsulted()
    query = compose_coverage_query(
        [s for s in weak], goal) if weak else goal[:300]
    for i, doc_id in enumerate(untouched):
        if should_cancel is not None and should_cancel():
            ledger.shortfall = "cancelled"
            return new_citations, "cancelled"
        if on_progress is not None:
            on_progress({"phase": "forced_pass", "docs_done": i,
                         "docs_total": len(untouched)})
        res = tools.invoke("search-doc", {"document_id": doc_id,
                                          "query": query,
                                          "top_k": _FORCED_TOP_K})
        if not getattr(res, "ok", False) or not isinstance(res.data, dict):
            ledger.failures[doc_id] = (getattr(res, "error", None)
                                       or "search-doc failed")[:200]
            continue
        hits = res.data.get("hits") or []
        # a successful query over the doc's index IS consultation ("full"
        # promises consulted, not read); zero hits just means it had nothing
        # for these sections
        ledger.mark(doc_id, "forced")
        cits = citations_from_hits(hits)
        new_citations.extend(cits)
        for c in cits:
            if c.quote:
                evidence.append(f"[{c.citation}] {c.quote}")
    if not evidence:
        return new_citations, None
    ev_block, used = [], 0
    for e in evidence:
        if used + len(e) > _EVIDENCE_CHAR_CAP:
            break
        ev_block.append(e)
        used += len(e)
    for res in weak:
        if should_cancel is not None and should_cancel():
            ledger.shortfall = "cancelled"
            return new_citations, "cancelled"
        if max_llm_calls is not None and counting.usage.llm_calls >= max_llm_calls:
            ledger.shortfall = "llm call cap"
            return new_citations, "call_cap"
        try:
            turn = counting.complete(
                [{"role": "system", "content": load_report_md()},
                 {"role": "user", "content": compose_forced_revision_prompt(
                     goal, res.title or res.key, res.content, ev_block)}], [])
        except CallCapExceeded:
            ledger.shortfall = "llm call cap"
            return new_citations, "call_cap"
        content, grade = split_grade_marker(turn.text or "")
        if content.strip():
            res.content = content
            res.filled = True
            res.note = ""
            # Re-grade from ONLY this section's own citations, never the
            # corpus-wide forced pool: the sweep hands every weak section the
            # same shared evidence block with no per-section attribution, so
            # crediting a section with docs the sweep merely touched would
            # inflate its distinct-doc count and let a 1-doc section read
            # "high". Same invariant the mining path holds (see _mine_corpus).
            # A section with no own citations honestly floors at "low"; the
            # run-level coverage verdict is applied later, once, by the caller.
            res.confidence = blend_confidence(
                grade, (own_cits or {}).get(res.key, []))
    return new_citations, None


def _digests_block(digests: dict[int, str], corpus_docs: dict | None) -> str:
    """Join per-doc digests into the prompt block, capped so a big corpus
    cannot blow the unit's context. Truncation is stated inline - a unit
    told 'these are all the digests' when they are not would trust a lie."""
    parts, used = [], 0
    for doc_id in sorted(digests):
        text = digests[doc_id].strip()
        if not text:
            continue
        name = (corpus_docs or {}).get(doc_id) or ""
        entry = f"[doc {doc_id} {name}] {text}".strip()
        if used + len(entry) > _DIGEST_BLOCK_CAP:
            parts.append("(further digests omitted: prompt budget)")
            break
        parts.append(entry)
        used += len(entry)
    return "\n".join(parts)


def _mine_corpus(ledger, sections, *, goal: str, tools, counting, budget,
                 reserve_calls: int, max_llm_calls, should_cancel,
                 on_progress):
    """Enforce `exhaustive` coverage: read every not-yet-read doc SYSTEM-side
    (get-doc; the model cannot skip a doc) and mine each slice with one
    metered call. Slices are budget-sized so small-window models survive
    whole documents without stage-D handoffs (fixed slicing, not model-driven
    state). reserve_calls keeps mining from starving the write phase: mining
    stops - honestly - while the section units can still afford their floor.

    Returns (digests, citations); mutates the ledger in place."""
    digests: dict[int, str] = {}
    citations: list = []
    docs = ledger.corpus_docs
    if docs is None:
        ledger.shortfall = "could not list corpus documents"
        return digests, citations
    slice_chars = max(4000, budget.max_context_chars // 2)
    todo = [d for d in sorted(docs) if ledger.consulted.get(d) != "read"]
    for i, doc_id in enumerate(todo):
        if should_cancel is not None and should_cancel():
            ledger.shortfall = "cancelled"
            return digests, citations
        if on_progress is not None:
            on_progress({"phase": "mining", "docs_done": i,
                         "docs_total": len(todo)})
        res = tools.invoke("get-doc", {"document_id": doc_id})
        if not getattr(res, "ok", False) or not isinstance(res.data, dict):
            ledger.failures[doc_id] = (getattr(res, "error", None)
                                       or "get-doc failed")[:200]
            continue
        text = res.data.get("text") or ""
        citations.append(Citation(
            document_id=doc_id, pipeline_id=res.data.get("pipeline_id"),
            pipeline=res.data.get("pipeline"), position=None,
            citation=f"document {doc_id} (whole text)", source=None,
            score=None, quote=text[:500]))
        slices = [text[j:j + slice_chars]
                  for j in range(0, len(text), slice_chars)] or [""]
        findings: list[str] = []
        capped = False
        for part_no, part in enumerate(slices, 1):
            if max_llm_calls is not None and \
                    max_llm_calls - counting.usage.llm_calls <= reserve_calls:
                ledger.shortfall = "llm call cap"
                capped = True
                break
            try:
                turn = counting.complete(
                    [{"role": "system", "content": MINING_MD},
                     {"role": "user", "content": compose_mining_prompt(
                         goal, sections, doc_id, docs.get(doc_id, ""),
                         part, part_no, len(slices))}], [])
            except CallCapExceeded:
                ledger.shortfall = "llm call cap"
                capped = True
                break
            reply = (turn.text or "").strip()
            if reply and reply.upper() != "NOTHING RELEVANT":
                findings.append(reply)
        if capped and not findings:
            # nothing mined: the read did not happen in any honest sense
            return digests, citations
        digests[doc_id] = "\n".join(findings)[:_DIGEST_CHAR_CAP]
        ledger.mark(doc_id, "read")
        if capped:
            return digests, citations
    return digests, citations


def _remaining_text(ledger) -> str:
    """The work-still-outstanding line a continuation is told to tackle:
    the corpus documents the run has not consulted yet (the ledger's own
    signal, same source the forced pass uses). Kept small - it rides in a
    prompt. When nothing is unconsulted (or the corpus size is unknown) the
    line says 'deepen and finish', never a misleading 'nothing left'."""
    un = ledger.unconsulted()
    if not un:
        return ("no unconsulted documents remain; deepen the weakest parts "
                "and finish from the evidence already gathered")
    return "documents not yet consulted: " + ", ".join(str(d) for d in un)


def _run_unit_with_handoffs(prompt, *, tools, llm, budget, autonomous_md,
                            should_cancel, unit_key, ledger, max_handoffs,
                            compose_continuation):
    """Run ONE bounded work unit, then keep it going across HANDOFFS when it
    runs out of round budget WITHOUT finishing.

    The frozen loop signals 'ran out of rounds, not done' with
    stop_reason == 'round_cap' (loop.py's forced synthesis, never reached when
    the model finishes on its own). On THAT signal - and only that; final,
    cancelled and no_tools_used are terminal - we spin a FRESH continuation
    unit that resumes from the partial draft + the docs already covered + the
    work still outstanding. research_agent stays frozen: a continuation is a
    brand-new run with a RESUME prompt, not a re-entered loop.

    Bounded three ways, all honest: max_handoffs caps how many continuations
    spawn; the shared max_llm_calls / CountingLlm backstop means a continuation
    that will not fit the remaining allowance is simply NOT spawned (greedy
    with a floor, exactly like the per-section quota); and each continuation's
    own round budget is re-derived from the allowance that is left, never
    exceeding the first unit's - so a continuation cannot starve later units.

    Returns (merged_report, handoffs). The merged Report takes the LAST unit's
    markdown (each continuation was told to keep+extend the prior draft, so its
    markdown is authoritative - concatenating would duplicate the kept portion)
    and stop_reason, with citations and run_log CONCATENATED across every unit
    (cross-unit citation de-dup stays the caller's job, via _dedupe_citations).
    handoffs is one artifact dict - the frozen 'handoff' shape - per
    continuation actually spawned. Each unit's citations are marked into the
    ledger here, so the caller must not mark them again."""
    report = research_agent.run(prompt, tools=tools, llm=llm, budget=budget,
                                autonomous_md=autonomous_md,
                                should_cancel=should_cancel)
    ledger.mark_citations(report.citations, "search")
    cits = list(report.citations)
    run_log = list(report.run_log)
    markdown = report.markdown
    stop = report.stop_reason
    handoffs: list[dict] = []
    cap = getattr(llm, "max_calls", None)

    for attempt in range(1, max_handoffs + 1):
        # only a budget-truncated unit is "unfinished" - nothing to continue
        # when the model finished, was cancelled, or degenerately said nothing
        if stop != "round_cap":
            break
        # a cancel mid-chain stops cleanly: keep the partial, spawn no more
        if should_cancel is not None and should_cancel():
            break
        # greedy-with-a-floor: if what allowance remains cannot fund even a
        # floor-sized unit, do not spawn one - an honest partial beats a unit
        # that would trip the backstop halfway through
        if cap is not None and (cap - llm.usage.llm_calls) < _MIN_UNIT_CALLS:
            break
        # re-derive this continuation's round budget from what is left, capped
        # by the ORIGINAL unit budget (never more rounds than the first unit).
        # A cap with no concrete budget falls back to the unit budget; the
        # backstop below still bounds the spend.
        cont_budget = budget
        if cap is not None and budget is not None:
            remaining_calls = cap - llm.usage.llm_calls
            cont_budget = replace(budget, max_rounds=max(
                1, min(budget.max_rounds, remaining_calls - 1)))
        docs_covered = sorted({c.document_id for c in cits
                               if c.document_id is not None})
        remaining = _remaining_text(ledger)
        # record the handoff BEFORE running: the attempt is spawned regardless
        # of how the continuation ends, and partial_chars refers to the draft
        # that was handed off (the pre-continuation markdown)
        handoffs.append({
            "kind": "handoff", "key": f"{unit_key}-h{attempt}",
            "payload": {"unit": unit_key, "attempt": attempt,
                        "trigger": "round_cap", "docs_covered": docs_covered,
                        "remaining": remaining,
                        "partial_chars": len(markdown or "")}})
        try:
            cont = research_agent.run(
                compose_continuation(markdown, docs_covered, remaining),
                tools=tools, llm=llm, budget=cont_budget,
                autonomous_md=autonomous_md, should_cancel=should_cancel)
        except CallCapExceeded:
            # the backstop tripped INSIDE the continuation: earlier units'
            # markdown + citations already live on the accumulators, so keep
            # them rather than lose the partial to a cap trip. (A generic
            # continuation crash is NOT caught here - the caller's per-section
            # handler owns crash semantics and the run's "failed" stop.)
            break
        ledger.mark_citations(cont.citations, "search")
        cits.extend(cont.citations)
        run_log.extend(cont.run_log)
        markdown = cont.markdown or markdown
        stop = cont.stop_reason

    merged = research_agent.Report(markdown=markdown, citations=cits,
                                   run_log=run_log, stop_reason=stop)
    return merged, handoffs


def run_goal(goal_type: str, spec: dict, *, corpus: str, tools, llm,
             budget=None, coverage: str = "search",
             guidance: str | None = None,
             prior_draft: str | None = None,
             prior_sections: list | None = None,
             prior_ledger: dict | None = None,
             max_llm_calls: int | None = None,
             should_cancel=None, on_progress=None) -> GoalRunResult:
    compiled = compile_spec(goal_type, spec)
    if coverage not in COVERAGE_MODES:
        raise ValueError(
            f"unknown coverage mode: {coverage!r} (supported: {COVERAGE_MODES})")
    counting = CountingLlm(llm, max_calls=max_llm_calls)
    # the ledger exists for EVERY run: search mode gets the honest account
    # ("consulted N of M"), full/exhaustive add enforcement on top. Built
    # before any LLM call so even a crashed run reports what it consulted.
    ledger = CoverageLedger(mode=coverage,
                            corpus_docs=list_corpus_docs(tools, corpus))
    ledger.merge_prior(prior_ledger)
    if goal_type == "report":
        return _run_report(compiled, corpus=corpus, tools=tools,
                           counting=counting,
                           budget=budget if budget is not None else research_agent.RunBudget(),
                           coverage=coverage, ledger=ledger,
                           guidance=guidance,
                           prior_sections=prior_sections or [],
                           max_llm_calls=max_llm_calls,
                           should_cancel=should_cancel,
                           on_progress=on_progress)
    # living-research: the stage-A single-unit path, deepened by coverage
    digests_text = None
    extra_citations: list = []
    if coverage == "exhaustive":
        budget = budget if budget is not None else research_agent.RunBudget()
        digests, mined_cits = _mine_corpus(
            ledger, compiled.sections, goal=compiled.goal, tools=tools,
            counting=counting, budget=budget,
            reserve_calls=(_MIN_UNIT_CALLS if max_llm_calls is not None else 0),
            max_llm_calls=max_llm_calls, should_cancel=should_cancel,
            on_progress=on_progress)
        extra_citations.extend(mined_cits)
        digests_text = _digests_block(digests, ledger.corpus_docs) or None
    prompt = compose_prompt(compiled, corpus=corpus, guidance=guidance,
                            prior_draft=prior_draft, digests_text=digests_text)
    if max_llm_calls is not None:
        budget = budget if budget is not None else research_agent.RunBudget()
        # REMAINING allowance, not max_llm_calls-1: mining already spent some
        remaining = max(0, max_llm_calls - counting.usage.llm_calls)
        budget = replace(budget, max_rounds=min(budget.max_rounds,
                                                max(0, remaining - 1)))
    report = research_agent.run(prompt, tools=tools, llm=counting,
                                budget=budget, should_cancel=should_cancel)
    ledger.mark_citations(report.citations, "search")
    markdown, stop, citations = (report.markdown, report.stop_reason,
                                 extra_citations + list(report.citations))
    if coverage == "full" and stop not in ("cancelled",):
        # the whole draft is the one weak "section": revise it once with any
        # forced evidence, so living-research gets the same guarantee
        body = SectionResult(key="body", content=markdown or "",
                             filled=bool((markdown or "").strip()))
        forced_cits, forced_halt = _forced_pass(
            ledger, [body], goal=compiled.goal, tools=tools,
            counting=counting, max_llm_calls=max_llm_calls,
            should_cancel=should_cancel, on_progress=on_progress,
            own_cits={"body": list(report.citations)})
        citations.extend(forced_cits)
        markdown = body.content
        if forced_halt is not None:
            stop = forced_halt
    return GoalRunResult(markdown=markdown, citations=_dedupe_citations(citations),
                         run_log=list(report.run_log), stop_reason=stop,
                         usage=counting.usage, ledger=ledger.to_dict())


def _dedupe_citations(cits: list) -> list:
    """Cross-unit de-dup with the SAME semantics as the loop's own _dedupe
    (which already ran within each unit): anonymous citations never collapse,
    and the same (document, quote) passage arriving via two tools - a search
    hit in one unit, a whole-text read in another - keeps the first,
    better-attributed occurrence. Duplicated rather than imported: the loop's
    helper is private and the research lane is frozen."""
    seen: set = set()
    seen_quotes: dict = {}   # qkey -> index in `out` of the kept occurrence
    out = []
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
                # Same passage already kept via another tool; keep the
                # better-attributed one. A precise search hit (real position)
                # beats a whole-text read (position=None), which the mining
                # phase appends FIRST - without this swap the reader would get
                # the generic "document N (whole text)" entry and lose the
                # section's exact citation, leaving a dangling body marker.
                idx = seen_quotes[qkey]
                if out[idx].position is None and c.position is not None:
                    out[idx] = c
                    seen.add(key)
                continue
            seen_quotes[qkey] = len(out)
        seen.add(key)
        out.append(c)
    return out


# shortfall label per halt/empty reason, woven into the carry note so an
# exported rerun says WHY a section was not revised this time
_SHORTFALL = {"call_cap": "llm call cap", "cancelled": "cancelled",
              "failed": "unit failed", "no_content": "no content produced"}


def _skipped_note(halted: str) -> str:
    """Note for a section skipped after the run already halted. "run failed"
    reads more sensibly than the bare "failed" halt token."""
    label = {"call_cap": "llm call cap", "cancelled": "cancelled",
             "failed": "run failed"}.get(halted, halted)
    return f"skipped: {label}"


def _carry_prior(res: SectionResult, prior: dict | None, shortfall: str) -> None:
    """A section ended unfilled this run; if the PRIOR run filled it, carry
    that content forward rather than regressing to a placeholder. WHY: a rerun
    exists to improve a report - starving one section (cap/cancel/crash/empty)
    should never lose good text the last run produced. The note records both
    the shortfall AND that the text is stale (not revised this run); confidence
    rides along from the prior so the reader is not told the carried text was
    freshly graded."""
    content = (prior or {}).get("content") or ""
    if not content.strip():
        return
    res.content = content
    res.filled = True
    conf = (prior or {}).get("confidence")
    res.confidence = conf if conf else blend_confidence(None, [])
    if res.note and res.note.startswith("unit failed:"):
        # the crash detail (exception name + truncated message) was already
        # recorded on res.note before this carry ran; keep it under the
        # "unit failed" sentinel so the exec adapter's note match still finds
        # run.error on a rerun that crashed but had prior content to carry
        detail = res.note[len("unit failed:"):].strip()
        res.note = f"unit failed (carried prior, not revised): {detail}"
    else:
        res.note = f"carried from prior, not revised: {shortfall}"


def _run_report(compiled, *, corpus, tools, counting, budget, coverage,
                ledger, guidance, prior_sections, max_llm_calls,
                should_cancel, on_progress):
    # keep the FULL prior dicts (content + confidence), not just content: a
    # section that ends unfilled carries the prior's content and confidence
    prior_by_key = {p.get("key"): p for p in prior_sections}
    report_md = load_report_md()
    results = [SectionResult(key=s.key, title=s.title)
               for s in compiled.sections]
    citations: list = []
    own_cits: dict[str, list] = {}   # section key -> its OWN citations, so a
                                     # forced-pass re-grade counts only the
                                     # section's own evidence, never the sweep
    run_log: list[dict] = []
    halted: str | None = None   # run-level early-stop reason, once set
    # run-level round_cap bubbles up ONLY from a unit that BOTH ran out of
    # rounds AND produced nothing (a section its own unit filled - even via
    # forced synthesis under a quota - is not a truncation to report)
    round_cap_empty = False

    digests_text = None
    mined_cits: list = []   # corpus-wide citations from the mining phase;
                            # added to the RUN-LEVEL citations list only -
                            # never folded into a per-section confidence
                            # blend (that would credit every section with
                            # docs it never itself cited)
    if coverage == "exhaustive":
        reserve = (_MIN_UNIT_CALLS * len(compiled.sections)
                   if max_llm_calls is not None else 0)
        digests, mined_cits = _mine_corpus(
            ledger, compiled.sections, goal=compiled.goal, tools=tools,
            counting=counting, budget=budget, reserve_calls=reserve,
            max_llm_calls=max_llm_calls, should_cancel=should_cancel,
            on_progress=on_progress)
        citations.extend(mined_cits)
        digests_text = _digests_block(digests, ledger.corpus_docs) or None

    for i, (section, res) in enumerate(zip(compiled.sections, results)):
        if halted is None and should_cancel is not None and should_cancel():
            halted = "cancelled"
            res.note = "cancelled"
        if halted is not None:
            res.note = res.note or _skipped_note(halted)
            _carry_prior(res, prior_by_key.get(section.key),
                         _SHORTFALL.get(halted, halted))
            continue
        unit_budget = budget
        if max_llm_calls is not None:
            remaining = max_llm_calls - counting.usage.llm_calls
            if remaining < _MIN_UNIT_CALLS:
                halted = "call_cap"
                res.note = "skipped: llm call cap"
                _carry_prior(res, prior_by_key.get(section.key),
                             _SHORTFALL["call_cap"])
                continue
            # greedy-with-floor: every unit that runs gets at least the
            # 2-call minimum; fair share only widens it (see module docstring)
            quota = max(_MIN_UNIT_CALLS, remaining // (len(results) - i))
            unit_budget = replace(budget, max_rounds=max(
                1, min(budget.max_rounds, quota - 1)))
        if on_progress is not None:
            on_progress({"phase": "running", "section": res.key,
                         "sections_done": i, "sections_total": len(results)})
        prior = prior_by_key.get(section.key)
        prompt = compose_section_prompt(
            compiled.goal, section, corpus=corpus, guidance=guidance,
            prior_content=(prior or {}).get("content"),
            digests_text=digests_text)
        calls_before = counting.usage.llm_calls
        try:
            unit = research_agent.run(prompt, tools=tools, llm=counting,
                                      budget=unit_budget,
                                      autonomous_md=report_md,
                                      should_cancel=should_cancel)
        except CallCapExceeded:
            # backstop tripped mid-unit: the unit's partial context dies but
            # every previously landed section survives - the whole point of
            # farming out bounded units
            res.note = "llm call cap"
            res.llm_calls = counting.usage.llm_calls - calls_before
            halted = "call_cap"
            _carry_prior(res, prior, _SHORTFALL["call_cap"])
            continue
        except Exception as e:
            # a unit crashing (a bad tool, a provider error, a malformed reply)
            # halts the run but must NOT discard sections that already landed -
            # the same partial-survival guarantee the call cap gives. The
            # message is truncated so a giant provider error can't bloat the
            # note (String(16) stop column holds only "failed").
            msg = f"{type(e).__name__}: {e}"[:200]
            res.note = f"unit failed: {msg}"
            res.llm_calls = counting.usage.llm_calls - calls_before
            halted = "failed"
            _carry_prior(res, prior, _SHORTFALL["failed"])
            continue
        res.llm_calls = counting.usage.llm_calls - calls_before
        res.stop_reason = unit.stop_reason
        for entry in unit.run_log:
            run_log.append({"section": res.key, **entry})
        if unit.stop_reason == "cancelled":
            res.note = "cancelled"
            halted = "cancelled"
            _carry_prior(res, prior, _SHORTFALL["cancelled"])
            continue
        content, grade = split_grade_marker(unit.markdown or "")
        res.confidence = blend_confidence(grade, unit.citations)
        own_cits[res.key] = list(unit.citations)
        citations.extend(unit.citations)
        ledger.mark_citations(unit.citations, "search")
        if content.strip():
            res.content = content
            res.filled = True
        else:
            res.note = "no content produced"
            # judge round_cap on the UNIT's own outcome, before any carry
            # fills content - carry must not mask a genuine truncation
            if unit.stop_reason == "round_cap":
                round_cap_empty = True
            _carry_prior(res, prior, _SHORTFALL["no_content"])

    if coverage == "full" and halted is None:
        forced_cits, forced_halt = _forced_pass(
            ledger, _weak_sections(results), goal=compiled.goal, tools=tools,
            counting=counting, max_llm_calls=max_llm_calls,
            should_cancel=should_cancel, on_progress=on_progress,
            own_cits=own_cits)
        citations.extend(forced_cits)
        if forced_halt is not None:
            halted = forced_halt
    elif coverage == "full" and halted is not None:
        # the run already stopped (cap/cancel/crash): coverage enforcement
        # cannot run, and the ledger must say so rather than stay silent
        ledger.shortfall = _SHORTFALL.get(halted, halted)

    coverage_ok = ledger.complete()
    for res in results:
        if not res.confidence:
            res.confidence = blend_confidence(None, [], coverage_ok=coverage_ok)
        elif coverage_ok is not None and "coverage_complete" not in res.confidence \
                and not (res.note or "").startswith(("carried from prior",
                                                     "unit failed (carried")):
            res.confidence = dict(res.confidence,
                                  coverage_complete=coverage_ok)
            if coverage_ok is False and res.confidence.get("level") == "high":
                res.confidence["level"] = "medium"
    if halted is not None:
        stop = halted
    elif round_cap_empty:
        stop = "round_cap"
    else:
        stop = "final"
    return GoalRunResult(markdown=render_report(compiled.title, results),
                         citations=_dedupe_citations(citations),
                         run_log=run_log, stop_reason=stop,
                         usage=counting.usage, sections=results,
                         ledger=ledger.to_dict())
