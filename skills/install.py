#!/usr/bin/env python3
"""Idempotent, append-only installer for madosho's agent pack.

Manages a sentinel-delimited block in a workspace's AGENTS.md / CLAUDE.md and copies
the two skills in. It NEVER overwrites a user's own content: the managed block is
appended if absent, replaced in place if present, and removable cleanly. Stdlib only.
"""
from __future__ import annotations

import pathlib

BEGIN = "<!-- BEGIN madosho (managed) -->"
END = "<!-- END madosho (managed) -->"


def upsert_block(text: str, body: str) -> str:
    """Return `text` with the managed block set to `body` - appended if absent,
    replaced in place if present. Content outside the markers is never touched."""
    block = f"{BEGIN}\n{body}\n{END}"
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        return text[:start] + block + text[end:]
    base = text.rstrip("\n")
    if base:
        return base + "\n\n" + block + "\n"
    return block + "\n"


def remove_block(text: str) -> str:
    """Return `text` with the managed block removed, tidying surrounding newlines.
    No-op if the block is absent. User content outside the markers is preserved."""
    if BEGIN not in text or END not in text:
        return text
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    after = text[end:]
    if after.startswith("\n"):
        after = after[1:]
    before = text[:start].rstrip("\n")
    return (before + "\n" + after) if before else after


def apply_to_file(path: pathlib.Path, body: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(upsert_block(text, body), encoding="utf-8")


def remove_from_file(path: pathlib.Path) -> None:
    if not path.exists():
        return
    path.write_text(remove_block(path.read_text(encoding="utf-8")), encoding="utf-8")


import argparse
import shutil

_PACK = pathlib.Path(__file__).resolve().parent
_SKILLS = ("madosho-search", "madosho-research")
_CLAUDE_BODY = "@AGENTS.md"


def _agents_body() -> str:
    return (_PACK / "AGENTS.md").read_text(encoding="utf-8").strip()


def install(target: pathlib.Path, skills_dir: pathlib.Path) -> None:
    apply_to_file(target / "AGENTS.md", _agents_body())
    apply_to_file(target / "CLAUDE.md", _CLAUDE_BODY)
    for name in _SKILLS:
        shutil.copytree(_PACK / name, skills_dir / name, dirs_exist_ok=True)


def uninstall(target: pathlib.Path, skills_dir: pathlib.Path) -> None:
    remove_from_file(target / "AGENTS.md")
    remove_from_file(target / "CLAUDE.md")
    for name in _SKILLS:
        shutil.rmtree(skills_dir / name, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="install.py",
        description="Install (or remove) madosho's agent skills + ambient hook into a workspace.")
    ap.add_argument("--target", default=".", help="workspace directory (default: .)")
    ap.add_argument("--skills-dir", default=".claude/skills", dest="skills_dir",
                    help="skills directory, relative to target (default: .claude/skills; "
                         "Codex/opencode users: pass your host's skills path)")
    ap.add_argument("--uninstall", action="store_true", help="remove what install added")
    args = ap.parse_args(argv)
    target = pathlib.Path(args.target).resolve()
    skills_dir = target / args.skills_dir
    if args.uninstall:
        uninstall(target, skills_dir)
        print(f"removed madosho agent pack from {target}")
    else:
        target.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)
        install(target, skills_dir)
        print(f"installed madosho agent pack into {target} "
              f"(skills -> {skills_dir}); AGENTS.md / CLAUDE.md updated append-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
