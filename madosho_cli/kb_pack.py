"""Pack an llmkb knowledge base folder into ONE markdown document.

madosho treats a whole KB as a single living document. This reader speaks the
llmkb FORMAT.md v1 contract (directory layout + kb.yaml identity) and imports
nothing from llmkb. Zero-dependency: kb.yaml is parsed with a minimal line scan
so madosho-cli stays stdlib-only.
"""
from __future__ import annotations

from pathlib import Path

_WIKI_SUBDIRS = ("summaries", "concepts", "entities")


class KbPackError(Exception):
    """The path is not a usable llmkb KB."""


def _scalar(raw: str) -> str:
    """Minimal YAML scalar cleanup for kb.yaml's flat lines: drop an inline
    comment on an unquoted value, then strip surrounding quotes. Enough for
    name/format; madosho-cli stays PyYAML-free."""
    v = raw.strip()
    if v[:1] in ("\"", "'"):
        # Quoted value: find the closing quote, discard everything after
        quote = v[0]
        end = v.find(quote, 1)
        if end != -1:
            v = v[:end+1]
    elif "#" in v:
        # Unquoted value: strip inline comment
        v = v.split("#", 1)[0].strip()
    return v.strip("\"'").strip()


def _read_identity(kb_dir: Path) -> dict:
    cfg = kb_dir / "kb.yaml"
    if not cfg.exists():
        raise KbPackError(f"no kb.yaml in {kb_dir}")
    name = None
    fmt: object = None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("name:"):
            name = _scalar(s[len("name:"):])
        elif s.startswith("format:"):
            val = _scalar(s[len("format:"):])
            fmt = int(val) if val.isdigit() else val
    if not name:
        raise KbPackError(f"kb.yaml in {kb_dir} has no 'name'")
    if fmt != 1:
        raise KbPackError(f"unsupported KB format {fmt!r} (expected 1)")
    return {"name": name, "format": fmt}


def pack_kb(kb_dir: str | Path) -> tuple[str, str]:
    """Return (filename, content) for a single madosho document."""
    kb_dir = Path(kb_dir)
    ident = _read_identity(kb_dir)
    parts: list[str] = [f"# Knowledge base: {ident['name']}\n"]
    index = kb_dir / "wiki" / "index.md"
    if index.exists():
        parts.append(index.read_text(encoding="utf-8").strip() + "\n")
    for sub in _WIKI_SUBDIRS:
        d = kb_dir / "wiki" / sub
        if not d.is_dir():
            continue
        for page in sorted(d.glob("*.md")):
            parts.append(f"\n<!-- page: wiki/{sub}/{page.name} -->\n")
            parts.append(page.read_text(encoding="utf-8").strip() + "\n")
    content = "\n".join(parts).strip() + "\n"
    return f"{ident['name']}.md", content
