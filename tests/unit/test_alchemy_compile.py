import pytest

from alchemy.compile import compile_spec
from alchemy.types import CompiledGoal


def test_living_research_compiles_to_one_section():
    out = compile_spec("living-research", {"goal": "find all vulns"})
    assert isinstance(out, CompiledGoal)
    assert out.goal == "find all vulns"
    assert len(out.sections) == 1
    assert out.sections[0].key == "body"
    assert out.sections[0].instruction == "find all vulns"


def test_unknown_goal_type_rejected():
    with pytest.raises(ValueError, match="unknown goal type"):
        compile_spec("unknown-type", {"goal": "x"})


def test_missing_goal_rejected():
    with pytest.raises(ValueError, match="goal"):
        compile_spec("living-research", {})
    with pytest.raises(ValueError, match="goal"):
        compile_spec("living-research", {"goal": "   "})


TEMPLATE = """\
# Vulnerability report

Assess the corpus for security problems.

## Summary

One paragraph for a busy reader.

## June incidents

Dig into the maintenance logs; list each incident with dates.

## June incidents

(duplicate heading on purpose)

## Appendix
"""


def test_report_compiles_headings_to_sections():
    cg = compile_spec("report", {"template": TEMPLATE})
    assert cg.title == "Vulnerability report"
    assert "Assess the corpus" in cg.goal
    keys = [s.key for s in cg.sections]
    assert keys == ["summary", "june-incidents", "june-incidents-2", "appendix"]
    assert cg.sections[0].title == "Summary"
    assert cg.sections[0].instruction == "One paragraph for a busy reader."
    # heading with no body: the heading itself is the instruction
    assert cg.sections[3].instruction == "Appendix"


def test_report_goal_defaults_when_no_preamble():
    cg = compile_spec("report", {"template": "## Only section\n\nWrite it.\n"})
    assert cg.title == ""
    assert cg.goal  # non-empty default goal statement
    assert len(cg.sections) == 1


def test_report_heading_inside_code_fence_is_not_a_section():
    t = "## Real\n\nBody with example:\n```\n## not a heading\n```\nmore.\n"
    cg = compile_spec("report", {"template": t})
    assert [s.key for s in cg.sections] == ["real"]
    assert "## not a heading" in cg.sections[0].instruction


def test_report_heading_inside_tilde_fence_is_not_a_section():
    # a ## inside a ~~~ fence is opaque, same as inside a ``` fence
    t = "## Real\n\nExample:\n~~~\n## not a heading\n~~~\nmore.\n"
    cg = compile_spec("report", {"template": t})
    assert [s.key for s in cg.sections] == ["real"]
    assert "## not a heading" in cg.sections[0].instruction


def test_report_backtick_inside_tilde_fence_does_not_close_it():
    # a ``` line inside a ~~~ fence must NOT close the tilde fence, so a ## AFTER
    # that backtick line - still inside the tilde fence - stays opaque
    t = ("## Real\n\nExample:\n~~~\n```\n## still not a heading\n~~~\nafter.\n")
    cg = compile_spec("report", {"template": t})
    assert [s.key for s in cg.sections] == ["real"]
    assert "## still not a heading" in cg.sections[0].instruction


def test_report_strips_leading_bom():
    # a UTF-8 BOM glued to the first line must not defeat "# "/"## " detection
    cg = compile_spec("report", {"template": "\ufeff## Only\n\nbody\n"})
    assert [s.key for s in cg.sections] == ["only"]
    cg2 = compile_spec("report", {"template": "\ufeff# T\n\n## A\n"})
    assert cg2.title == "T"


def test_report_requires_template():
    with pytest.raises(ValueError):
        compile_spec("report", {})
    with pytest.raises(ValueError):
        compile_spec("report", {"template": "   "})


def test_report_requires_at_least_one_section():
    with pytest.raises(ValueError):
        compile_spec("report", {"template": "# Title\n\njust prose\n"})


def test_living_research_still_single_body_section():
    cg = compile_spec("living-research", {"goal": "map the vulns"})
    assert [s.key for s in cg.sections] == ["body"]
    assert cg.sections[0].title == ""
    assert cg.title == ""


def test_report_section_key_collision_avoided():
    """Regression: headings that slug to foo/foo-2/foo should get distinct keys.

    When a heading like "Foo 2" slugs to "foo-2" (a suffix form), and then
    another heading "Foo" tries to become "foo-2" (its second occurrence),
    the dedup must avoid the collision by incrementing further.
    """
    template = """\
## Foo

First foo.

## Foo 2

This slugs to foo-2, not "Foo" plus suffix.

## Foo

Second foo - must not collide with "Foo 2".
"""
    cg = compile_spec("report", {"template": template})
    keys = [s.key for s in cg.sections]
    # All keys must be distinct
    assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"
    # The three sections should have three distinct keys
    assert len(keys) == 3
    # "Foo" becomes "foo", "Foo 2" becomes "foo-2" (first base "foo-2"),
    # "Foo" again becomes "foo-3" (not "foo-2" which is taken)
    assert keys == ["foo", "foo-2", "foo-3"]


def test_slug_of_symbols_only_heading_is_section():
    from alchemy.compile import _slug
    assert _slug("") == "section"
    assert _slug("!!!") == "section"
    # and end to end: a symbols-only heading still yields a usable key
    compiled = compile_spec("report", {"template": "## ???\n\nbody"})
    assert compiled.sections[0].key == "section"


def test_report_fields_compile_to_sections():
    spec = {"title": "Vuln report", "goal": "Assess the corpus.",
            "fields": [
                {"key": "summary", "title": "Summary",
                 "instruction": "One paragraph for a busy reader."},
                {"key": "incidents", "title": "Incidents",
                 "instruction": "List each incident with dates."},
            ]}
    cg = compile_spec("report", spec)
    assert cg.title == "Vuln report"
    assert "Assess the corpus" in cg.goal
    assert [s.key for s in cg.sections] == ["summary", "incidents"]
    assert cg.sections[0].title == "Summary"
    assert cg.sections[0].instruction == "One paragraph for a busy reader."


def test_report_fields_instruction_falls_back_to_title_then_key():
    # instruction is the fill directive; a minimal field must still tell the
    # unit SOMETHING, so it falls back to the human title, then the bare key
    spec = {"fields": [
        {"key": "a", "title": "Alpha"},   # no instruction -> the title
        {"key": "b"},                     # no instruction, no title -> the key
    ]}
    cg = compile_spec("report", spec)
    assert cg.sections[0].instruction == "Alpha"
    assert cg.sections[1].instruction == "b"


def test_report_fields_duplicate_keys_deduped():
    spec = {"fields": [
        {"key": "risk", "instruction": "first"},
        {"key": "risk", "instruction": "second"},
    ]}
    cg = compile_spec("report", spec)
    assert [s.key for s in cg.sections] == ["risk", "risk-2"]


def test_report_fields_empty_list_raises():
    with pytest.raises(ValueError):
        compile_spec("report", {"fields": []})


def test_report_field_missing_key_raises():
    with pytest.raises(ValueError):
        compile_spec("report", {"fields": [{"title": "no key here"}]})


def test_report_requires_template_or_fields():
    # a report spec with NEITHER format is the API's 400 path
    with pytest.raises(ValueError):
        compile_spec("report", {"goal": "neither template nor fields"})
