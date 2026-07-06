"""the MCP example pack compiles, exposes --help, and is ASCII-only. No live
stack or subprocess server is launched in the fast suite."""
from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACK = ROOT / "examples" / "mcp"


def test_demo_compiles():
    py_compile.compile(str(PACK / "mcp_demo.py"), doraise=True)


def test_demo_help():
    proc = subprocess.run([sys.executable, str(PACK / "mcp_demo.py"), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage" in proc.stdout.lower()


def test_pack_is_ascii():
    for p in PACK.rglob("*"):
        if p.is_file() and p.suffix != ".pyc":
            p.read_bytes().decode("ascii", "strict")  # raises if non-ASCII


def test_pack_readme_is_ascii():
    assert (PACK / "README.md").read_text(encoding="utf-8").isascii()


def test_host_config_snippet_is_valid_json():
    data = json.loads((PACK / "claude_desktop_config.example.json").read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "madosho" in data["mcpServers"]
