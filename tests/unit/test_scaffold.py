import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

import madosho

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def test_package_importable():
    assert madosho.__version__ == "0.1.0"


def test_dependency_floors_are_tested_floors():
    """Version floors are tested floors: a floor the suite hasn't run against is
    a lie — a user installing at it gets raw AttributeError/TypeError instead of
    our friendly errors. For every [local] dep present in this environment, the
    declared floor must sit in the installed (tested) major.minor series, and
    must be a floor (>=), never an upper pin."""
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    for req in (Requirement(r) for extra in ("docling", "lancedb", "models", "qdrant")
                for r in extras[extra]):
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == ">=", \
            f"{req}: declare exactly one >= floor, no upper pins"
        try:
            installed = Version(metadata.version(req.name))
        except metadata.PackageNotFoundError:
            continue        # extra not installed here; nothing was tested
        floor = Version(specs[0].version)
        assert req.specifier.contains(installed), \
            f"{req.name}: installed {installed} does not satisfy declared floor {floor}"
        assert (floor.major, floor.minor) == (installed.major, installed.minor), \
            (f"{req.name}: floor {floor} is not the tested series "
             f"{installed.major}.{installed.minor} — run the suite against the floor "
             f"or raise it to the tested version")
