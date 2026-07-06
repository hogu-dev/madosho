import subprocess
import sys
import venv
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "tests" / "fixtures" / "toy_plugin"

CHECK = """
import logging
from pathlib import Path

from madosho.core.hooks import ResolutionContext
from madosho.core.meta import ComponentKind
from madosho.core.protocols import Parser, RuntimeContext
from madosho.core.registry import Registry

reg = Registry()
reg.discover_entry_points()
assert "toy" in reg.names(ComponentKind.PARSER), reg.names(ComponentKind.PARSER)
cls = reg.load_class(ComponentKind.PARSER, "toy")
assert cls.META.org == "toyco"
rt = RuntimeContext(corpus="c", data_dir=Path("."), cache_dir=Path("."),
                    logger=logging.getLogger("check"))
inst = reg.resolve(ComponentKind.PARSER, "toy", {}, rt, ResolutionContext(corpus="c"))
assert isinstance(inst, Parser)
print("PLUGIN-OK")
"""


def test_separate_wheel_is_discovered_and_usable(tmp_path):
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True)
    py = env_dir / "bin" / "python"

    def run(*cmd):
        r = subprocess.run([str(py), *cmd], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"command failed (rc={r.returncode}):\n{r.stderr.strip()}")
        return r

    # real packaging path: needs network for dependency metadata (slow-marked on purpose)
    run("-m", "pip", "install", "--quiet", str(REPO))           # madosho core, no extras
    run("-m", "pip", "install", "--quiet", str(PLUGIN))         # the separate adapter
    out = run("-c", CHECK)
    assert "PLUGIN-OK" in out.stdout
