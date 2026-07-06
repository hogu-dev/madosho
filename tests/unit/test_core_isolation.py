import ast
from pathlib import Path

import madosho.core

CORE = Path(madosho.core.__file__).parent
# the fence deliberately flags TYPE_CHECKING-only imports too: core stays dependency-free even for typing
FORBIDDEN = ("madosho.adapters", "madosho.operators", "madosho.cli")


def iter_imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module
            elif node.level == 1:           # from . / from .x — inside madosho.core
                yield f"madosho.core.{node.module or ''}"
            elif node.level == 2:           # from .. / from ..x — siblings of core
                yield f"madosho.{node.module or ''}"


def test_core_imports_no_adapters_operators_or_cli():
    offenders = [
        f"{py.name}: {mod}"
        for py in CORE.rglob("*.py")
        for mod in iter_imports(py)
        if mod.startswith(FORBIDDEN)
    ]
    assert offenders == [], f"core must stay adapter-free, found: {offenders}"
