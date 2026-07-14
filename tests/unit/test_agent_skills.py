"""the two portable skills are well-formed on the core SKILL.md fields only
(name + description + body) and reference real madosho tools. No dependency on the
experimental `allowed-tools` field (only 2 of the 3 target hosts parse it)."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACK = ROOT / "skills"


def _read_skill(path: pathlib.Path) -> tuple[dict, str]:
    """Minimal, dependency-free SKILL.md reader: returns (frontmatter, body).
    Frontmatter is the block between the first two `---` lines; we pull the simple
    top-level `key:` lines (enough to guard name + description)."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} must open with YAML frontmatter"
    _, fm, body = text.split("---\n", 2)
    front: dict[str, str] = {}
    for line in fm.splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, val = line.partition(":")
            front[key.strip()] = val.strip()
    return front, body


def test_basic_skill_wellformed():
    front, body = _read_skill(PACK / "madosho-search" / "SKILL.md")
    assert front.get("name") == "madosho-search"
    assert len(front.get("description", "")) >= 30   # a real trigger description
    assert "madosho-cli" in body and "--json" in body
    for tool in ("search", "search-doc", "get-doc", "list-corpora",
                 "list-documents", "list-pipelines", "list-goals",
                 "goal-runs", "export-goal-run", "run-goal"):
        assert tool in body, f"basic skill body must mention {tool}"


def test_basic_skill_is_ascii():
    text = (PACK / "madosho-search" / "SKILL.md").read_text(encoding="utf-8")
    assert text.isascii(), "SKILL.md must be ASCII-only"


def test_autonomous_skill_wellformed():
    front, body = _read_skill(PACK / "madosho-research" / "SKILL.md")
    assert front.get("name") == "madosho-research"
    assert len(front.get("description", "")) >= 30
    # it composes the basic skill and dispatches a subagent over the playbook
    assert "madosho-search" in body
    assert "autonomous.md" in body
    assert "subagent" in body.lower()


def test_bundled_autonomous_md_matches_source():
    # no-drift guard: the bundled playbook must be byte-identical to the single source
    src = (ROOT / "research_agent" / "autonomous.md").read_bytes()
    bundled = (PACK / "madosho-research" / "autonomous.md").read_bytes()
    assert bundled == src, "bundled autonomous.md drifted from research_agent/autonomous.md"


def test_autonomous_skill_is_ascii():
    text = (PACK / "madosho-research" / "SKILL.md").read_text(encoding="utf-8")
    assert text.isascii()
