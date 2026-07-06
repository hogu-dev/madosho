"""Guard tests for examples/distributed/proof.py.

Mirrors the pattern used in test_web_login.py for login.py:
  - ASCII-only source
  - stdlib-only imports (the script must run without installing anything)
  - parses and compiles without error
  - docstring asserts: pass-through proof and key-in-env are documented
"""
import ast
import pathlib
import py_compile

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "examples" / "distributed" / "proof.py"


def test_distributed_example_is_ascii():
    """Every byte in proof.py must be valid ASCII."""
    _SCRIPT.read_text().encode("ascii")


def test_distributed_example_is_stdlib_only():
    """proof.py must import only stdlib modules -- no third-party deps."""
    src = _SCRIPT.read_text()
    tree = ast.parse(src)

    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported |= {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    stdlib = {"json", "os", "sys", "urllib"}
    assert imported <= stdlib, (
        f"distributed example must be stdlib-only; found third-party: "
        f"{imported - stdlib}"
    )


def test_distributed_example_compiles():
    """proof.py must byte-compile without errors."""
    py_compile.compile(str(_SCRIPT), doraise=True)


def test_distributed_example_documents_passthrough_proof():
    """The module docstring must state the pass-through proof logic."""
    src = _SCRIPT.read_text()
    low = src.lower()

    # The script must document that it proves pass-through behavior.
    assert "pass-through" in low or "passthrough" in low, (
        "docstring must explain the pass-through proof"
    )
    # The 403 scope-enforcement result must be explained.
    assert "403" in src, "docstring must mention the 403 outcome for a read key"
    # The key must come from env, never be hardcoded.
    assert "MADOSHO_API_KEY" in src, "script must read the key from MADOSHO_API_KEY"
    # The toolserver URL must be overridable via env.
    assert "MADOSHO_TOOLSERVER_URL" in src, (
        "script must read the toolserver URL from MADOSHO_TOOLSERVER_URL"
    )
