from __future__ import annotations

from madosho.core.meta import ComponentKind
from madosho.core.registry import Registry

# Kinds the config form / pipeline create form let a user pick. (store/operator
# stay fixed for now; parser is included so a new pipeline can vary the extractor.)
_FORM_KINDS = [ComponentKind.PARSER, ComponentKind.CHUNKER,
               ComponentKind.EMBEDDER, ComponentKind.RERANKER]


def list_components() -> dict[str, list[dict]]:
    """Group available components by kind for the config form's menus."""
    registry = Registry()
    registry.discover_entry_points()
    out: dict[str, list[dict]] = {}
    for kind in _FORM_KINDS:
        rows = []
        for name in registry.names(kind):
            if registry.spec(kind, name).hidden:
                continue                     # testing fakes: resolvable, never listed
            # Hard slot dependencies travel with every row so the form can enforce
            # them live: {other_slot: [allowed names]}. Empty map = unconstrained.
            requires = {slot: list(allowed)
                        for slot, allowed in registry.spec(kind, name).requires}
            try:
                cls = registry.load_class(kind, name)
                meta = cls.META
                opts = getattr(cls, "Options", None)
                schema = opts.model_json_schema() if opts is not None else None
                rows.append({"name": name, "license": meta.license, "org": meta.org,
                             "origin_tier": meta.origin_tier.value,
                             "hardware": meta.hardware.value,
                             "install_extra": meta.install_extra,
                             "requires": requires, "options_schema": schema})
            except Exception:
                rows.append({"name": name, "license": None, "org": None,
                             "origin_tier": None, "hardware": None,
                             "install_extra": None, "requires": requires,
                             "options_schema": None})
        out[kind.value] = rows
    return out
