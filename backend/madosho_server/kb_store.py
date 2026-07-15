"""madosho's own copy of the llmkb v1 format (write side included).

madosho owns knowledge bases server-side: each KB is an llmkb-format folder on
disk. This module creates that folder and reads/writes format-correct pages
WITHOUT importing the private `llmkb` package - it extends the vendored-reader
precedent set by `madosho_cli/kb_pack.py`. PyYAML is already a backend dep, so
serialization matches llmkb's `serialize_page` exactly.
"""
from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

import yaml

_TYPE_TO_SUBDIR = {
    "summary": "wiki/summaries",
    "concept": "wiki/concepts",
    "entity": "wiki/entities",
}
_SUBDIRS = ("raw", "wiki/summaries", "wiki/concepts", "wiki/entities")
# Human labels for the index, in FORMAT order.
_INDEX_SECTIONS = (("Summaries", "summaries"), ("Concepts", "concepts"),
                   ("Entities", "entities"))
_FENCE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class KbStoreError(Exception):
    """Any KB folder/page operation that cannot be completed as asked."""


def kb_root(base_dir: str, kb_id: int) -> Path:
    return Path(base_dir) / f"kb-{kb_id}"


def _slug(title: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", title.strip().lower()).strip("-.")
    if not slug:
        raise KbStoreError(f"title has no usable characters: {title!r}")
    return slug


def _serialize(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    body = (body or "").rstrip("\n")
    if body:
        return f"---\n{front}\n---\n\n{body}\n"
    return f"---\n{front}\n---\n"


def _parse(text: str) -> tuple[dict, str]:
    m = _FENCE.match(text)
    if not m:
        raise KbStoreError("page is missing a '---' frontmatter block")
    meta = yaml.safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise KbStoreError("page frontmatter must be a YAML mapping")
    return meta, m.group(2)


def _page_dict(path: Path) -> dict:
    meta, body = _parse(path.read_text(encoding="utf-8"))
    return {
        "type": str(meta.get("type", "")),
        "title": str(meta.get("title", "")),
        "slug": path.stem,
        "description": str(meta.get("description", "")),
        "tags": list(meta.get("tags") or []),
        "timestamp": str(meta.get("timestamp", "")),
        "sources": list(meta.get("sources") or []),
        "body": body.strip("\n"),
    }


def _summary(path: Path) -> dict:
    d = _page_dict(path)
    return {"type": d["type"], "title": d["title"], "slug": d["slug"],
            "description": d["description"]}


def create_kb(base_dir: str, kb_id: int, name: str) -> Path:
    root = kb_root(base_dir, kb_id)
    if (root / "kb.yaml").exists():
        raise KbStoreError(f"KB kb-{kb_id} already exists on disk")
    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    config = {"name": name, "description": "", "format": 1,
              "created": date.today().isoformat()}
    (root / "kb.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "log.md").write_text("# Log\n", encoding="utf-8")
    return root


def delete_kb(base_dir: str, kb_id: int) -> None:
    shutil.rmtree(kb_root(base_dir, kb_id), ignore_errors=True)


def _page_path(root: Path, type: str, title: str) -> Path:
    if type not in _TYPE_TO_SUBDIR:
        raise KbStoreError(f"invalid page type: {type!r} (summary|concept|entity)")
    subdir = root / _TYPE_TO_SUBDIR[type]
    path = subdir / (_slug(title) + ".md")
    # Containment backstop: a crafted title must never escape its subdir.
    if subdir.resolve() != path.resolve().parent:
        raise KbStoreError(f"refusing to write outside the KB: {title!r}")
    return path


def _find_by_slug(root: Path, slug: str) -> Path | None:
    # Reject anything that isn't a single, contained filename component -
    # a traversal slug (containing "/", "\\", or "..") must never let the
    # lookup escape the KB folder (mirrors _page_path's containment check).
    if slug != Path(slug).name or slug in ("", ".", "..") or "/" in slug or "\\" in slug:
        return None
    for sub in _TYPE_TO_SUBDIR.values():
        base = (root / sub).resolve()
        cand = base / f"{slug}.md"
        if cand.resolve().parent != base:
            continue
        if cand.exists():
            return cand
    return None


def _append_log(root: Path, operation: str, title: str) -> None:
    line = f"## [{date.today().isoformat()}] {operation} | {title}\n"
    with (root / "wiki" / "log.md").open("a", encoding="utf-8") as fh:
        fh.write(line)


def reindex(root: Path) -> None:
    lines = ["# Index\n"]
    for label, sub in _INDEX_SECTIONS:
        pages = sorted((root / "wiki" / sub).glob("*.md"))
        if not pages:
            continue
        lines.append(f"\n## {label}\n")
        for p in pages:
            s = _summary(p)
            lines.append(f"- [[{s['title']}]] - {s['description']}\n")
    (root / "wiki" / "index.md").write_text("".join(lines), encoding="utf-8")


def add_page(root: Path, *, type: str, title: str, description: str,
             tags: list[str] | None = None, sources: list | None = None,
             body: str = "") -> dict:
    if not title.strip():
        raise KbStoreError("title is required")
    path = _page_path(root, type, title)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise KbStoreError(f"a page titled {title!r} already exists")
    meta = {"type": type, "title": title, "description": description,
            "tags": list(tags or []), "timestamp": date.today().isoformat(),
            "sources": list(sources or [])}
    path.write_text(_serialize(meta, body), encoding="utf-8")
    _append_log(root, "add-page", title)
    reindex(root)
    return _page_dict(path)


def edit_page(root: Path, slug: str, *, description: str | None = None,
              tags: list[str] | None = None, sources: list | None = None,
              body: str | None = None) -> dict:
    """Rewrite a page's mutable fields. Title and type are identity in P1 and
    are not editable (changing them would move the file)."""
    path = _find_by_slug(root, slug)
    if path is None:
        raise KbStoreError(f"no page with slug {slug!r}")
    cur = _page_dict(path)
    meta = {"type": cur["type"], "title": cur["title"],
            "description": cur["description"] if description is None else description,
            "tags": cur["tags"] if tags is None else list(tags),
            "timestamp": cur["timestamp"],
            "sources": cur["sources"] if sources is None else list(sources)}
    new_body = cur["body"] if body is None else body
    path.write_text(_serialize(meta, new_body), encoding="utf-8")
    _append_log(root, "edit-page", cur["title"])
    reindex(root)
    return _page_dict(path)


def move_page(src_root: Path, slug: str, *, dest_root: Path, new_type: str) -> dict:
    """Relocate a page to another KB (`dest_root`) and/or a different `new_type`.
    Every field but `type` is carried over unchanged; the file moves between the
    type subdirs (and KB folders). Errors on a missing source, a no-op move, or a
    title collision at the destination. Both KBs are reindexed and logged."""
    src_path = _find_by_slug(src_root, slug)
    if src_path is None:
        raise KbStoreError(f"no page with slug {slug!r}")
    cur = _page_dict(src_path)
    dest_path = _page_path(dest_root, new_type, cur["title"])
    if dest_path.resolve() == src_path.resolve():
        raise KbStoreError("page is already in that knowledge base and type")
    if dest_path.exists():
        raise KbStoreError(f"a page titled {cur['title']!r} already exists")
    meta = {"type": new_type, "title": cur["title"],
            "description": cur["description"], "tags": list(cur["tags"]),
            "timestamp": cur["timestamp"], "sources": list(cur["sources"])}
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(_serialize(meta, cur["body"]), encoding="utf-8")
    src_path.unlink()
    for root in {src_root.resolve(): src_root, dest_root.resolve(): dest_root}.values():
        _append_log(root, "move-page", cur["title"])
        reindex(root)
    return _page_dict(dest_path)


def get_page(root: Path, slug: str) -> dict | None:
    path = _find_by_slug(root, slug)
    return _page_dict(path) if path is not None else None


def read_index(root: Path) -> str:
    idx = root / "wiki" / "index.md"
    return idx.read_text(encoding="utf-8") if idx.exists() else "# Index\n"


def list_pages(root: Path) -> list[dict]:
    out: list[dict] = []
    for sub in _TYPE_TO_SUBDIR.values():
        for p in sorted((root / sub).glob("*.md")):
            out.append(_summary(p))
    return out


def search_pages(root: Path, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits: list[dict] = []
    for sub in _TYPE_TO_SUBDIR.values():
        for p in sorted((root / sub).glob("*.md")):
            d = _page_dict(p)
            hay = f"{d['title']}\n{d['description']}\n{d['body']}".lower()
            if q in hay:
                hits.append({"type": d["type"], "title": d["title"],
                             "slug": d["slug"], "description": d["description"]})
    return hits


def import_from_folder(base_dir: str, kb_id: int, name: str,
                       src_root: Path) -> Path:
    """Create a fresh server-owned KB and copy every page from an unpacked
    llmkb folder into it (validated through add_page so the result is
    format-clean and reindexed)."""
    dest = create_kb(base_dir, kb_id, name)
    for type_, sub in _TYPE_TO_SUBDIR.items():
        for p in sorted((Path(src_root) / sub).glob("*.md")):
            d = _page_dict(p)
            try:
                add_page(dest, type=d["type"] or type_, title=d["title"],
                         description=d["description"], tags=d["tags"],
                         sources=d["sources"], body=d["body"])
            except KbStoreError:
                continue  # skip a malformed/duplicate source page, keep importing
    return dest
