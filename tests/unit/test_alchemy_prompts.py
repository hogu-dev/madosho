from alchemy.compile import compile_spec
from alchemy.prompts import compose_prompt
from alchemy.types import CompiledGoal


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


from alchemy.prompts import compose_coverage_query, compose_forced_revision_prompt
from alchemy.types import Section


def test_coverage_query_prefers_weak_sections_and_caps_length():
    secs = [Section(key="one", instruction="i" * 400, title="Heading One")]
    q = compose_coverage_query(secs, goal="overall goal")
    assert "Heading One" in q
    assert len(q) <= 300


def test_coverage_query_falls_back_to_goal():
    q = compose_coverage_query([], goal="overall goal text")
    assert q == "overall goal text"


def test_coverage_query_falls_back_when_section_has_no_topical_signal():
    # living-research hands _forced_pass a bare structural section (key="body",
    # no title, no instruction). Its key is NOT topical, so the query must fall
    # back to the goal - not degenerate to the literal string "body", which
    # would make the forced sweep search every doc for a meaningless word.
    from alchemy.types import SectionResult
    body = SectionResult(key="body", content="draft")
    q = compose_coverage_query([body], goal="what causes X in Y")
    assert q == "what causes X in Y"


def test_forced_revision_prompt_carries_evidence_and_current_text():
    p = compose_forced_revision_prompt(
        "the goal", "Findings", "current body",
        ["[doc 7 @2] quote one", "[doc 9 @0] quote two"])
    assert "the goal" in p
    assert "Findings" in p
    assert "current body" in p
    assert "quote one" in p and "quote two" in p
    assert "CONFIDENCE:" in p          # revision must re-grade itself
    assert "unchanged" in p.lower()    # explicit permission to keep the text


# --- Stage C task 6: mining prompt + digests block ---------------------------

from alchemy.prompts import MINING_MD, compose_mining_prompt


def test_mining_prompt_names_doc_sections_and_part():
    secs = [Section(key="one", instruction="find X", title="One")]
    p = compose_mining_prompt("goal", secs, 7, "a.pdf", "the text", 2, 3)
    assert "document 7" in p and "a.pdf" in p
    assert "part 2 of 3" in p
    assert "One" in p and "find X" in p
    assert "the text" in p
    assert "NOTHING RELEVANT" in MINING_MD


def test_section_prompt_carries_digests_block():
    sec = Section(key="one", instruction="find X", title="One")
    p = compose_section_prompt("goal", sec, corpus="c",
                               digests_text="[doc 7 a.pdf] facts")
    assert "[doc 7 a.pdf] facts" in p
    # and absent when None (stage-B call sites unchanged)
    p2 = compose_section_prompt("goal", sec, corpus="c")
    assert "digest" not in p2.lower()


def test_goal_prompt_carries_digests_block():
    compiled = CompiledGoal(goal="g", sections=[Section(key="body",
                                                        instruction="g")])
    p = compose_prompt(compiled, corpus="c", digests_text="[doc 7] facts")
    assert "[doc 7] facts" in p
