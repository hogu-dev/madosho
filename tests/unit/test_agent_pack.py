"""the agent pack scripts compile, expose --help, are ASCII-only, and the demo
can read both skills. No live stack touched in the fast suite."""
from __future__ import annotations

import importlib.util
import py_compile
import subprocess
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACK = ROOT / "skills"
SCRIPTS = ("install.py", "research_trigger.py", "agent_pack_demo.py")


@pytest.mark.parametrize("name", SCRIPTS)
def test_pack_script_compiles(name):
    py_compile.compile(str(PACK / name), doraise=True)


@pytest.mark.parametrize("name", SCRIPTS)
def test_pack_script_help(name):
    proc = subprocess.run([sys.executable, str(PACK / name), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage" in proc.stdout.lower()


def test_pack_is_ascii():
    for p in PACK.rglob("*"):
        if p.is_file() and p.suffix != ".pyc":
            assert p.read_bytes().decode("ascii", "strict")  # raises if non-ASCII


def test_pack_readme_is_ascii():
    text = (PACK / "README.md").read_text(encoding="utf-8")
    assert text.isascii()


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "agent_pack_demo", PACK / "agent_pack_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_reads_both_skills():
    demo = _load_demo()
    lines = demo.check_skills()
    joined = "\n".join(lines)
    assert "madosho-search" in joined
    assert "madosho-research" in joined
