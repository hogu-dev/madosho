"""The append-only, idempotent, never-clobber skills installer core."""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_install():
    path = ROOT / "skills" / "install.py"
    spec = importlib.util.spec_from_file_location("agent_install", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


install = _load_install()


def test_upsert_into_empty():
    out = install.upsert_block("", "HELLO")
    assert install.BEGIN in out and install.END in out and "HELLO" in out


def test_upsert_preserves_user_content():
    out = install.upsert_block("MY OWN NOTES\n", "HELLO")
    assert out.startswith("MY OWN NOTES")
    assert install.BEGIN in out and "HELLO" in out


def test_upsert_is_idempotent():
    once = install.upsert_block("user\n", "HELLO")
    twice = install.upsert_block(once, "HELLO")
    assert twice == once


def test_upsert_updates_in_place_without_touching_user_content():
    base = install.upsert_block("BEFORE\n", "OLD")
    base = base + "AFTER-USER-EDIT\n"          # user appended their own line after the block
    updated = install.upsert_block(base, "NEW")
    assert "NEW" in updated and "OLD" not in updated
    assert "BEFORE" in updated and "AFTER-USER-EDIT" in updated   # user content survives


def test_remove_block_leaves_user_content():
    with_block = install.upsert_block("MY OWN NOTES\n", "HELLO")
    removed = install.remove_block(with_block)
    assert "HELLO" not in removed and install.BEGIN not in removed
    assert "MY OWN NOTES" in removed


def test_remove_block_absent_is_noop():
    assert install.remove_block("nothing here\n") == "nothing here\n"


SKILLS = ("madosho-search", "madosho-research")


def test_install_creates_blocks_and_copies_skills(tmp_path):
    rc = install.main(["--target", str(tmp_path)])
    assert rc == 0
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert install.BEGIN in agents and "madosho" in agents
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert install.BEGIN in claude and "@AGENTS.md" in claude
    for name in SKILLS:
        assert (tmp_path / ".claude" / "skills" / name / "SKILL.md").exists()
    # the bundled playbook came along with the autonomous skill
    assert (tmp_path / ".claude" / "skills" / "madosho-research"
            / "autonomous.md").exists()


def test_install_preserves_existing_user_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My project rules\nDo the thing.\n",
                                        encoding="utf-8")
    install.main(["--target", str(tmp_path)])
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "My project rules" in agents and "Do the thing." in agents
    assert install.BEGIN in agents


def test_install_is_idempotent(tmp_path):
    install.main(["--target", str(tmp_path)])
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    install.main(["--target", str(tmp_path)])
    second = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert first == second
    for name in SKILLS:
        assert (tmp_path / ".claude" / "skills" / name / "SKILL.md").exists()


def test_uninstall_removes_blocks_and_skills(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My project rules\n", encoding="utf-8")
    install.main(["--target", str(tmp_path)])
    rc = install.main(["--target", str(tmp_path), "--uninstall"])
    assert rc == 0
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert install.BEGIN not in agents and "My project rules" in agents
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert install.BEGIN not in claude
    for name in SKILLS:
        assert not (tmp_path / ".claude" / "skills" / name).exists()


def test_install_into_nonexistent_target_creates_it(tmp_path):
    fresh = tmp_path / "brand" / "new" / "workspace"
    rc = install.main(["--target", str(fresh)])
    assert rc == 0
    assert (fresh / "AGENTS.md").exists()
    assert (fresh / ".claude" / "skills" / "madosho-search" / "SKILL.md").exists()
