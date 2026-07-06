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
        compile_spec("report", {"goal": "x"})   # report is stage B


def test_missing_goal_rejected():
    with pytest.raises(ValueError, match="goal"):
        compile_spec("living-research", {})
    with pytest.raises(ValueError, match="goal"):
        compile_spec("living-research", {"goal": "   "})
