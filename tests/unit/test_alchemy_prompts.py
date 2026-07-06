from alchemy.compile import compile_spec
from alchemy.prompts import compose_prompt


def _compiled():
    return compile_spec("living-research", {"goal": "map the vulns"})


def test_initial_prompt_carries_goal_and_corpus():
    p = compose_prompt(_compiled(), corpus="secdocs")
    assert "map the vulns" in p
    assert "secdocs" in p
    assert "Prior draft" not in p


def test_revision_prompt_carries_draft_and_guidance():
    p = compose_prompt(_compiled(), corpus="secdocs",
                       guidance="section 3 is thin",
                       prior_draft="# old draft\nbody")
    assert "map the vulns" in p
    assert "# old draft" in p
    assert "section 3 is thin" in p
    # revision framing must ask to REVISE, not start over
    assert "revise" in p.lower()


def test_guidance_without_prior_draft_is_fine():
    p = compose_prompt(_compiled(), corpus="7", guidance="focus on 2024")
    assert "focus on 2024" in p
