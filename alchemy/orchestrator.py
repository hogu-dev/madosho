"""The stage-A orchestrator: one goal run = one work unit.

Deliberately thin today: compile the spec, compose the prompt, meter the
LLM, drive ONE bounded research loop, return its result with accounting.
Stage B grows planning (many units, one per section) and stage C coverage
enforcement - both live HERE, behind the same run_goal signature, which is
WHY the server adapter and CLI never need to change when the engine deepens.

max_llm_calls enforcement: the loop spends exactly one LLM call per round
plus one forced-synthesis call when the round cap trips (loop.py), so
clamping rounds to max_llm_calls - 1 keeps total calls <= max_llm_calls
while still ending with a draft. CountingLlm's own cap is the backstop for
the day that call pattern changes.
"""
from __future__ import annotations

from dataclasses import replace

import research_agent

from .compile import compile_spec
from .llm import CountingLlm
from .prompts import compose_prompt
from .types import GoalRunResult


def run_goal(goal_type: str, spec: dict, *, corpus: str, tools, llm,
             budget=None, guidance: str | None = None,
             prior_draft: str | None = None,
             max_llm_calls: int | None = None,
             should_cancel=None) -> GoalRunResult:
    compiled = compile_spec(goal_type, spec)
    prompt = compose_prompt(compiled, corpus=corpus, guidance=guidance,
                            prior_draft=prior_draft)
    counting = CountingLlm(llm, max_calls=max_llm_calls)
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
