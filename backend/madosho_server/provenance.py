"""Document provenance labels. A generated document (a draft alchemy ingested
back into the library) carries a human-readable suffix on every hit, citation,
and listing so a reader can tell model-written material from source material at
a glance. Kept in one tiny module with NO imports so both the query plane
(query_core) and the control plane (db.Document, api) can depend on it without a
cycle."""
from __future__ import annotations


def origin_label(origin: str, meta: dict | None) -> str:
    """The human suffix rendered on every hit/citation/row for a generated
    document, e.g. '[generated: find_vuln v2]'. Empty for source docs so normal
    output is byte-identical to before this feature existed."""
    if origin != "generated":
        return ""
    m = meta or {}
    g, v = m.get("goal"), m.get("version")
    # Prefer "goal vN"; fall back to the bare goal; finally a generic tag, so a
    # partially-populated meta dict never renders "vNone" or an empty bracket.
    tag = f"{g} v{v}" if g and v is not None else (g or "alchemy")
    return f"[generated: {tag}]"
