# backend/madosho_server/traits.py
"""Cheap, deterministic document traits derived from parsed artifacts.

These feed the rule-based static rater. No LLM, no network. The artifacts dict
is the kernel's `Artifacts.model_dump(mode="json")` (see Document.artifacts):
`chunks` carry text + 0-indexed `page`; `blocks` carry a `kind` and provenance.
"""
from __future__ import annotations


def _pages(chunks: list[dict], blocks: list[dict]) -> int:
    seen = [c["page"] for c in chunks if c.get("page") is not None]
    seen += [b.get("provenance", {}).get("page") for b in blocks
             if b.get("provenance", {}).get("page") is not None]
    return (max(seen) + 1) if seen else 1       # pages are 0-indexed


def extract_traits(artifacts: dict) -> dict:
    chunks = artifacts.get("chunks", []) or []
    blocks = artifacts.get("blocks", []) or []
    page_count = _pages(chunks, blocks)
    chunk_count = len(chunks)
    table_count = sum(1 for b in blocks if b.get("kind") == "table")
    total_chars = sum(len(c.get("text", "")) for c in chunks)
    return {
        "page_count": page_count,
        "chunk_count": chunk_count,
        "table_count": table_count,
        "avg_chunk_chars": round(total_chars / chunk_count, 1) if chunk_count else 0.0,
        "text_density": round(total_chars / page_count, 1),     # chars per page
        "table_density": round(table_count / page_count, 3),
    }
