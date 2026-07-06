"""Origin guard: every non-hidden built-in component is US_SRC or ALLIED_SRC.

docs/COMPLIANCE.md promises that the DEFAULT install contains only components
whose developing org and base-weight lineage sit inside the documented
US/allied origin set; CN/other-source components live in
separate opt-in bundles. This test keeps that packaging promise from rotting
silently.

It is a packaging guard, not a runtime gate: the Registry here deliberately
skips entry-point discovery, because installed bundles ARE allowed to add
components of any origin tier -- that is the whole point of the bundles.
"""

from madosho.core.meta import OriginTier
from madosho.core.registry import BUILTINS, Registry

ALLOWED = (OriginTier.US_SRC, OriginTier.ALLIED_SRC)


def test_builtin_components_are_us_or_allied_src():
    registry = Registry()  # builtins only; no discover_entry_points() on purpose
    offending = []
    missing = []
    for spec in BUILTINS:
        if spec.hidden:
            continue
        try:
            meta = registry.load_class(spec.kind, spec.name).META
        except Exception:
            # Optional extra not installed in this environment; the full CI
            # environment installs everything, so the guard is complete there.
            missing.append(spec.name)
            continue
        if meta.origin_tier not in ALLOWED:
            offending.append((spec.kind.value, spec.name, meta.origin_tier.value))
    assert not offending, (
        f"components in the default install outside the US/allied set: {offending}; "
        "cn_oth_src components belong in the opt-in bundles (docs/COMPLIANCE.md)"
    )
