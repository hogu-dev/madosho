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

Stage C grows coverage enforcement here, behind the same run_goal signature
- WHY the server adapter and CLI never change when the engine deepens.
"""
from __future__ import annotations

from dataclasses import replace

import research_agent

from .compile import compile_spec
from .confidence import blend_confidence, split_grade_marker
from .llm import CallCapExceeded, CountingLlm
from .prompts import compose_prompt, compose_section_prompt, load_report_md
from .render import render_report
from .types import GoalRunResult, SectionResult

_MIN_UNIT_CALLS = 2   # one working round + the forced synthesis


def run_goal(goal_type: str, spec: dict, *, corpus: str, tools, llm,
             budget=None, guidance: str | None = None,
             prior_draft: str | None = None,
             prior_sections: list | None = None,
             max_llm_calls: int | None = None,
             should_cancel=None, on_progress=None) -> GoalRunResult:
    compiled = compile_spec(goal_type, spec)
    counting = CountingLlm(llm, max_calls=max_llm_calls)
    if goal_type == "report":
        return _run_report(compiled, corpus=corpus, tools=tools,
                           counting=counting,
                           budget=budget if budget is not None else research_agent.RunBudget(),
                           guidance=guidance,
                           prior_sections=prior_sections or [],
                           max_llm_calls=max_llm_calls,
                           should_cancel=should_cancel,
                           on_progress=on_progress)
    # living-research: the stage-A single-unit path, unchanged
    prompt = compose_prompt(compiled, corpus=corpus, guidance=guidance,
                            prior_draft=prior_draft)
    if max_llm_calls is not None:
        budget = budget if budget is not None else research_agent.RunBudget()
        budget = replace(budget, max_rounds=min(budget.max_rounds,
                                                max(0, max_llm_calls - 1)))
    report = research_agent.run(prompt, tools=tools, llm=counting,
                                budget=budget, should_cancel=should_cancel)
    return GoalRunResult(markdown=report.markdown,
                         citations=list(report.citations),
                         run_log=list(report.run_log),
                         stop_reason=report.stop_reason,
                         usage=counting.usage)


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


def _run_report(compiled, *, corpus, tools, counting, budget, guidance,
                prior_sections, max_llm_calls, should_cancel, on_progress):
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
            prior_content=(prior or {}).get("content"))
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
        citations.extend(unit.citations)
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

    for res in results:   # skipped/failed sections still report numbers
        if not res.confidence:
            res.confidence = blend_confidence(None, [])
    if halted is not None:
        stop = halted
    elif round_cap_empty:
        stop = "round_cap"
    else:
        stop = "final"
    return GoalRunResult(markdown=render_report(compiled.title, results),
                         citations=_dedupe_citations(citations),
                         run_log=run_log, stop_reason=stop,
                         usage=counting.usage, sections=results)
