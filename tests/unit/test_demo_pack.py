"""the demo orchestrator + the aggregated runbook/README are correct and
ASCII-only. No live stack is launched in the fast suite."""
from __future__ import annotations

import argparse
import importlib.util
import py_compile
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "demo"


def _load_demo_all():
    spec = importlib.util.spec_from_file_location("demo_all", DEMO / "demo_all.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_all"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_demo_all_compiles():
    py_compile.compile(str(DEMO / "demo_all.py"), doraise=True)


def test_demo_all_help():
    proc = subprocess.run([sys.executable, str(DEMO / "demo_all.py"), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage" in proc.stdout.lower()


def test_build_argv_forwards_only_accepted_flags():
    mod = _load_demo_all()
    opts = argparse.Namespace(corpus="demo", model="m", provider="p", with_llm=True)
    by_label = {d.label: d for d in mod.DEMOS}
    # api-contract accepts corpus/model/with_llm
    argv_contract = mod.build_argv(by_label["api-contract"], opts)
    assert "--corpus" in argv_contract and "demo" in argv_contract
    assert "--model" in argv_contract and "--with-llm" in argv_contract
    # chat-frontends takes corpus/with_llm but NOT --model: its proxy chat needs a
    # *virtual* model name and self-resolves it, so the raw --model must not leak
    # through (forwarding it would 404 the chat). See the DEMOS comment in demo_all.py.
    argv_chat = mod.build_argv(by_label["chat-frontends"], opts)
    assert "--corpus" in argv_chat and "--with-llm" in argv_chat
    assert "--model" not in argv_chat
    # mcp accepts only corpus - no model/provider/with-llm leak through
    argv_mcp = mod.build_argv(by_label["mcp"], opts)
    assert "--corpus" in argv_mcp
    assert "--with-llm" not in argv_mcp
    assert "--model" not in argv_mcp
    assert "--provider" not in argv_mcp


def test_build_argv_omits_unset_flags():
    mod = _load_demo_all()
    opts = argparse.Namespace(corpus=None, model=None, provider=None, with_llm=False)
    argv = mod.build_argv(mod.DEMOS[0], opts)
    assert argv[:1] == [sys.executable]
    assert "--corpus" not in argv and "--with-llm" not in argv


def test_summarize_exit_code(capsys):
    mod = _load_demo_all()
    assert mod.summarize([("a", True, ""), ("b", True, "")]) == 0
    assert mod.summarize([("a", True, ""), ("b", False, "boom")]) == 1
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" in out


def test_demos_point_at_real_files():
    mod = _load_demo_all()
    assert len(mod.DEMOS) == 4
    for d in mod.DEMOS:
        assert (ROOT / d.path).exists(), d.path


PACK_DEMO_PATHS = [
    "examples/api-contract/contract_demo.py",
    "examples/chat-frontends/chat_frontends_demo.py",
    "examples/mcp/mcp_demo.py",
    "skills/agent_pack_demo.py",
]


def test_demo_readme_is_ascii():
    assert (DEMO / "README.md").read_text(encoding="utf-8").isascii()


def test_demo_all_is_ascii():
    assert (DEMO / "demo_all.py").read_text(encoding="utf-8").isascii()


def test_demo_readme_references_every_pack_and_the_orchestrator():
    text = (DEMO / "README.md").read_text(encoding="utf-8")
    for path in PACK_DEMO_PATHS:
        assert path in text, f"demo README does not reference {path}"
    assert "demo_all.py" in text
    # the two interactive doors are documented as manual walks
    assert "examples/chat-frontends" in text
    assert "examples/mcp" in text


def test_readme_is_ascii():
    assert (ROOT / "README.md").read_text(encoding="utf-8").isascii()


def test_readme_not_stale():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    # the external doors are pointed at where they now live
    for token in ("examples/api-contract", "examples/chat-frontends",
                  "examples/mcp", "examples/demo", "skills/"):
        assert token in text, f"README missing pointer {token}"
    # the service planes are named
    assert "8001" in text  # query plane
