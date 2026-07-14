"""Spec compilation: every goal type collapses to the same CompiledGoal.

living-research (spec = {"goal": "..."}) compiles to a single untitled
section keyed "body". report has two FORMATS on the same seam: a markdown
`template` (spec = {"template": "<markdown>"}) parses `## ` headings into
sections, and a structured schema (spec = {"fields": [...]}) turns each typed
field into one section. Neither format touches the orchestrator - that seam
is the whole point of compiling, and it is why stage D's fields format cost
zero engine changes.
"""
from __future__ import annotations

import re

from .types import CompiledGoal, Section

GOAL_TYPES = ("living-research", "report")

_DEFAULT_REPORT_GOAL = "Fill in the report sections from the corpus evidence."


def compile_spec(goal_type: str, spec: dict) -> CompiledGoal:
    if goal_type == "living-research":
        # guard non-string goals (e.g. a JSON number) here, not just empty
        # ones: this is the single validation the API now delegates to, so a
        # bad type must raise ValueError (-> 400), never an AttributeError
        raw = spec.get("goal")
        goal = raw.strip() if isinstance(raw, str) else ""
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
    """Dispatch the report goal type to its FORMAT parser.

    A report is authored in one of two formats on the SAME seam: a markdown
    `template` (headings become sections) or a typed `fields` list (each field
    IS a section). Both land in the identical CompiledGoal, so the engine never
    learns which the user chose - that is why a new format costs zero engine
    changes. `fields` is checked first so it wins if a spec somehow carries
    both. A report spec with NEITHER key is uncompilable and raises ValueError,
    which the API turns into a 400 at create time (api.py delegates all spec
    validation here)."""
    if "fields" in spec:
        return _compile_report_fields(spec)
    if "template" in spec:
        return _compile_report_template(spec)
    raise ValueError(
        "report spec must carry either a 'template' (markdown) or "
        "'fields' (typed list)")


def _compile_report_fields(spec: dict) -> CompiledGoal:
    """Typed fields -> CompiledGoal.

    A field is {"key": str, "title"?: str, "instruction"?: str} and becomes
    exactly one Section - the typed analog of a template's `## ` heading. `key`
    is slugged and deduped identically to headings (a repeated "risk" stays
    addressable as risk / risk-2), so confidence and citations attribute per
    section the same way regardless of format. `title` is the human heading the
    renderer re-emits. `instruction` is the fill directive; it is OPTIONAL and
    falls back to the title, then the key, so a bare {"key": "summary"} is a
    legal one-line field. Optional top-level spec["goal"] is the preamble and
    spec["title"] is the report H1 (mirroring the template path, where those
    come from the leading prose and `# ` line). WHY a list, not a JSON object:
    order is the report's structure and object key order is not guaranteed
    across producers."""
    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("report 'fields' must be a non-empty list")
    sections: list[Section] = []
    used_keys: set[str] = set()
    for i, fld in enumerate(fields):
        if not isinstance(fld, dict):
            raise ValueError(f"report field {i} must be an object")
        raw_key = fld.get("key")
        base = _slug(raw_key) if isinstance(raw_key, str) and raw_key.strip() else ""
        if not base:
            raise ValueError(f"report field {i} must carry a non-empty 'key'")
        # dedup exactly as the heading path does: a repeated key gets a -N
        # suffix so every section stays individually addressable
        suffix = 1
        key = base
        while key in used_keys:
            suffix += 1
            key = f"{base}-{suffix}"
        used_keys.add(key)
        raw_title = fld.get("title")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        raw_instr = fld.get("instruction")
        instr = raw_instr.strip() if isinstance(raw_instr, str) else ""
        instruction = instr or title or key
        sections.append(Section(key=key, instruction=instruction, title=title))
    raw_goal = spec.get("goal")
    preamble = raw_goal.strip() if isinstance(raw_goal, str) else ""
    raw_report_title = spec.get("title")
    title = raw_report_title.strip() if isinstance(raw_report_title, str) else ""
    goal = "\n\n".join(p for p in (title, preamble) if p) or _DEFAULT_REPORT_GOAL
    return CompiledGoal(goal=goal, sections=sections, title=title)


def _compile_report_template(spec: dict) -> CompiledGoal:
    """Markdown template -> CompiledGoal.

    Rules: the first `# ` line is the report title; any other prose before
    the first `## ` heading is the goal preamble; each `## ` heading opens a
    section whose body (until the next `## `) is its instruction. Fenced code
    blocks are opaque - a `## ` inside a fence is template content, not a
    heading. Both backtick (```) and tilde (~~~) fences count, and a fence is
    closed only by its OWN marker: a ``` line inside a ~~~ fence does not close
    it (and vice versa), so a heading buried in a tilde fence stays opaque. A
    heading with an empty body means "the heading IS the instruction" (a bare
    skeleton template is legal)."""
    template = spec.get("template")
    if not isinstance(template, str) or not template.strip():
        raise ValueError("report spec must carry a non-empty 'template'")
    # strip one leading UTF-8 BOM: Windows editors save UTF-8-with-BOM, and a
    # BOM glued to the first character defeats the "# "/"## " prefix checks
    if template.startswith("\ufeff"):
        template = template[1:]
    title = ""
    preamble: list[str] = []
    raw_sections: list[tuple[str, list[str]]] = []
    fence: str | None = None   # the marker (``` or ~~~) that OPENED the fence
    for line in template.splitlines():
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```"):
                fence = "```"
            elif stripped.startswith("~~~"):
                fence = "~~~"
        elif stripped.startswith(fence):
            fence = None
        in_fence = fence is not None
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
