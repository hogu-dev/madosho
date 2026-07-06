"""Spec compilation: every goal type collapses to the same CompiledGoal.

living-research (spec = {"goal": "..."}) compiles to a single untitled
section keyed "body". report (spec = {"template": "<markdown>"}) parses the
template's `## ` headings into sections WITHOUT touching the orchestrator -
that seam is the whole point of compiling. A later structured-schema format
(stage D) is one more branch here, zero engine changes.
"""
from __future__ import annotations

import re

from .types import CompiledGoal, Section

GOAL_TYPES = ("living-research", "report")

_DEFAULT_REPORT_GOAL = "Fill in the report sections from the corpus evidence."


def compile_spec(goal_type: str, spec: dict) -> CompiledGoal:
    if goal_type == "living-research":
        goal = (spec.get("goal") or "").strip()
        if not goal:
            raise ValueError("spec must carry a non-empty 'goal'")
        return CompiledGoal(goal=goal,
                            sections=[Section(key="body", instruction=goal)])
    if goal_type == "report":
        return _compile_report(spec)
    raise ValueError(f"unknown goal type: {goal_type!r} (supported: {GOAL_TYPES})")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "section"


def _compile_report(spec: dict) -> CompiledGoal:
    """Markdown template -> CompiledGoal.

    Rules: the first `# ` line is the report title; any other prose before
    the first `## ` heading is the goal preamble; each `## ` heading opens a
    section whose body (until the next `## `) is its instruction. Fenced
    code blocks are opaque - a `## ` inside ``` is template content, not a
    heading. A heading with an empty body means "the heading IS the
    instruction" (a bare skeleton template is legal)."""
    template = spec.get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError("report spec must carry a non-empty 'template'")
    title = ""
    preamble: list[str] = []
    raw_sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in template.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            raw_sections.append((line[3:].strip(), []))
            continue
        if raw_sections:
            raw_sections[-1][1].append(line)
        elif not in_fence and line.startswith("# ") and not title:
            title = line[2:].strip()
        else:
            preamble.append(line)
    if not raw_sections:
        raise ValueError(
            "report template needs at least one '## ' section heading")
    sections: list[Section] = []
    used_keys: set[str] = set()
    for heading, body_lines in raw_sections:
        base = _slug(heading)
        suffix = 1
        key = base
        while key in used_keys:
            suffix += 1
            key = f"{base}-{suffix}"
        used_keys.add(key)
        instruction = "\n".join(body_lines).strip() or heading
        sections.append(Section(key=key, instruction=instruction, title=heading))
    preamble_text = "\n".join(preamble).strip()
    goal = "\n\n".join(p for p in (title, preamble_text) if p) or _DEFAULT_REPORT_GOAL
    return CompiledGoal(goal=goal, sections=sections, title=title)
