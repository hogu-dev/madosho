from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "madosho-kb" / "SKILL.md"


def test_skill_exists_and_is_ascii():
    text = SKILL.read_text(encoding="utf-8")
    text.encode("ascii")  # raises if any non-ASCII (matches repo public-doc rule)


def test_skill_names_the_key_commands():
    text = SKILL.read_text(encoding="utf-8")
    assert "import-kb" in text
    assert "llmkb add-page" in text
    assert "madosho-cli search" in text
