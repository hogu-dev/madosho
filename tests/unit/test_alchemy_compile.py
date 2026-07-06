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
