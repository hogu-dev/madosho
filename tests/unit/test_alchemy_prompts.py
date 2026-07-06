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


from alchemy.prompts import compose_section_prompt, load_report_md
from alchemy.types import Section


def test_report_md_states_the_output_contract():
    md = load_report_md()
    assert "CONFIDENCE:" in md
    assert "ONE section" in md


def test_section_prompt_carries_goal_section_and_corpus():
    p = compose_section_prompt(
        "Vulnerability report", Section(key="summary", instruction="One paragraph.",
                                        title="Summary"), corpus="secdocs")
    assert "Vulnerability report" in p
    assert "Summary" in p
    assert "One paragraph." in p
    assert "'secdocs'" in p
    # initial run: no revision or guidance blocks
    assert "Prior section" not in p
    assert "guidance" not in p


def test_section_prompt_revision_and_guidance_blocks():
    p = compose_section_prompt(
        "goal", Section(key="june", instruction="dig", title="June"),
        corpus="c", guidance="cover the June incidents",
        prior_content="old section text")
    assert "old section text" in p
    assert "cover the June incidents" in p
    # prior draft comes BEFORE guidance so the steer reads as the last word
    assert p.index("old section text") < p.index("cover the June incidents")


def test_section_prompt_falls_back_to_key_when_untitled():
    p = compose_section_prompt("g", Section(key="body", instruction="i"),
                               corpus="c")
    assert "body" in p
