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
from .prompts import (MINING_MD, compose_coverage_query,
                      compose_forced_revision_prompt, compose_mining_prompt,
                      compose_prompt, compose_section_prompt, load_report_md)
from .render import render_report
from .types import GoalRunResult, SectionResult

_MIN_UNIT_CALLS = 2   # one working round + the forced synthesis
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
                 max_llm_calls, should_cancel, on_progress):
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
            # revised with forced evidence: re-blend from the forced
            # citations (per-section attribution of forced hits is not
            # tracked; the pass-level citations are the honest basis)
            res.confidence = blend_confidence(grade, new_citations)
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
            should_cancel=should_cancel, on_progress=on_progress)
        citations.extend(forced_cits)
        markdown = body.content
        if forced_halt is not None:
            stop = forced_halt
    return GoalRunResult(markdown=markdown, citations=citations,
                         run_log=list(report.run_log), stop_reason=stop,
                         usage=counting.usage, ledger=ledger.to_dict())


def _dedupe_citations(cits: list) -> list:
    """Cross-unit de-dup: two sections legitimately citing the same chunk
    should yield one run-level citation. Keyed like the loop's own de-dup
    (doc/pipeline/position) plus the quote, without reaching into the loop's
    private helper."""
    seen, out = set(), []
    for c in cits:
        key = (c.document_id, c.pipeline_id, c.position, c.quote)
        if key in seen:
            continue
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
    run_log: list[dict] = []
    halted: str | None = None   # run-level early-stop reason, once set
    # run-level round_cap bubbles up ONLY from a unit that BOTH ran out of
    # rounds AND produced nothing (a section its own unit filled - even via
    # forced synthesis under a quota - is not a truncation to report)
    round_cap_empty = False

    digests_text = None
    mined_cits: list = []   # folded into every section's confidence blend
                            # below - a section that relied on injected
                            # digests (no tool call of its own) must still
                            # get credit for the docs the mining phase read
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
        # exhaustive mode's digests rode in the prompt as TEXT, not tool
        # calls, so unit.citations alone would blind the blend to whatever
        # the mining phase already read; mined_cits is [] outside exhaustive
        # mode, so this is a no-op there (identical to stage-B behavior)
        res.confidence = blend_confidence(grade, unit.citations + mined_cits)
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
            should_cancel=should_cancel, on_progress=on_progress)
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
