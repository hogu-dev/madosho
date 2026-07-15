"""Page-level semantic index over KB pages.

The KB store (kb_store.py) is a plain-markdown wiki whose only retrieval is a
lexical substring scan. This module adds the semantic half: one dense vector
per page, held in a per-KB qdrant collection `madosho_kb_<id>`, reusing the
corpus kernel's embedder and QdrantStore unchanged. The query plane RRF-fuses
these semantic hits with the lexical search_pages results; this module owns
only the vector side (embed, upsert, delete, query).

Page-level (not chunk-level) by design: a KB page is a single conceptual unit,
so one vector per page indexes it for "find the right page" discovery, after
which the caller fetches the whole page via get-kb-page. `page_embed_text`
embeds exactly the fields the lexical scan reads (title + description + body)
so the two halves see the same surface.

The store/embedder are duck-typed (the kernel's QdrantStore + StEmbedder in
production, fakes in tests) so this module never imports heavy model code.
"""
from __future__ import annotations

from madosho.core.types import Chunk, EmbeddedChunk, Hit, IndexSpec, Vector

_DENSE = "dense"
_RRF_K = 60          # reciprocal-rank-fusion damping, matching the corpus query plane

_EMBEDDER = None


def kb_collection(kb_id: int) -> str:
    """The qdrant collection name for a KB, mirroring the per-pipeline
    `madosho_<corpus>` convention."""
    return f"madosho_kb_{kb_id}"


def get_embedder():
    """Process-cached KB embedder (granite default). Loads the heavy model once
    per process (worker or query plane); the lazy import keeps this module free
    of sentence-transformers until a caller actually embeds."""
    global _EMBEDDER
    if _EMBEDDER is None:
        from madosho.adapters.st_models.embedder import StEmbedder
        _EMBEDDER = StEmbedder()
    return _EMBEDDER


def open_store(qdrant_url: str, kb_id: int):
    """A QdrantStore bound to this KB's collection (lazy qdrant import)."""
    from madosho.adapters.qdrant.store import QdrantStore
    return QdrantStore(options=QdrantStore.Options(
        url=qdrant_url, collection=kb_collection(kb_id)))


def rrf_fuse(rankings: list[list[str]], k: int = _RRF_K) -> list[str]:
    """Reciprocal-rank fusion of several ranked slug lists into one best-first
    list (deduplicated). A slug present in more lists, and higher in them,
    scores higher. Same RRF the corpus query plane uses to merge index pools."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, slug in enumerate(ranking):
            scores[slug] = scores.get(slug, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda s: scores[s], reverse=True)


def page_embed_text(page: dict) -> str:
    """The text embedded for a page: title + description + body, the same
    fields kb_store.search_pages scans lexically. Empty parts are dropped."""
    parts = [page.get("title") or "", page.get("description") or "", page.get("body") or ""]
    return "\n\n".join(p for p in parts if p).strip()


def _page_chunk(kb_id: int, page: dict) -> Chunk:
    """One page -> one Chunk keyed by slug (id == doc_id == slug), carrying the
    summary fields the search response returns without a disk read."""
    slug = page["slug"]
    return Chunk(
        id=slug, doc_id=slug, text=page_embed_text(page),
        metadata={"kb_id": str(kb_id), "slug": slug, "type": page.get("type") or "",
                  "title": page.get("title") or "", "description": page.get("description") or ""})


def _spec(embedder) -> IndexSpec:
    # Dense-only: the lexical half lives in kb_store, so no bm25 sparse index.
    return IndexSpec(indexes=[_DENSE], vectors={_DENSE: embedder.dims})


def index_page(store, embedder, kb_id: int, page: dict) -> None:
    """Embed one page and upsert it (deterministic point id on slug, so this is
    an idempotent overwrite on edit)."""
    store.ensure_schema(_spec(embedder))
    chunk = _page_chunk(kb_id, page)
    vector: Vector = embedder.embed([chunk.text])[0]
    store.upsert([EmbeddedChunk(chunk=chunk, vectors={_DENSE: vector})])


def remove_page(store, slug: str) -> None:
    """Drop a page's vector (doc_id == slug). Used when a page moves out of a KB."""
    store.delete([slug])


def reindex(store, embedder, kb_id: int, pages: list[dict]) -> int:
    """(Re)embed a whole KB in one batch and return the page count. Existing
    points for unchanged slugs are overwritten in place; this does not prune
    slugs that vanished (whole-KB rebuilds recreate the collection instead)."""
    store.ensure_schema(_spec(embedder))
    chunks = [_page_chunk(kb_id, p) for p in pages]
    if not chunks:
        return 0
    vectors = embedder.embed([c.text for c in chunks])
    store.upsert([EmbeddedChunk(chunk=c, vectors={_DENSE: v})
                  for c, v in zip(chunks, vectors)])
    return len(chunks)


def search(store, embedder, query: str, k: int = 20) -> list[Hit]:
    """Embed the query and return the k nearest page vectors as Hits (chunk.id
    == slug). The caller maps these to page summaries and fuses with lexical."""
    # A read-side store instance hasn't seen ensure_schema yet; run it (on an
    # existing collection it only validates dims) so semantic_search has a spec.
    store.ensure_schema(_spec(embedder))
    qvec: Vector = embedder.embed([query])[0]
    return store.semantic_search(qvec, k)


def _summary(page_or_meta: dict, slug: str) -> dict:
    return {"slug": slug, "type": page_or_meta.get("type") or "",
            "title": page_or_meta.get("title") or "",
            "description": page_or_meta.get("description") or ""}


def fuse(lexical: list[dict], semantic_hits: list[Hit], limit: int = 20) -> list[dict]:
    """RRF-fuse lexical page summaries (kb_store.search_pages) with semantic
    Hits (search()) into one best-first summary list. Each side contributes a
    ranking of slugs; a page found on either side is returned, so semantic
    recall augments (never shrinks) the lexical result. Semantic hits carry the
    summary fields in chunk.metadata, so a page found only semantically still
    returns a full summary."""
    by_slug: dict[str, dict] = {}
    lex_slugs: list[str] = []
    for p in lexical:
        by_slug[p["slug"]] = _summary(p, p["slug"])
        lex_slugs.append(p["slug"])
    sem_slugs: list[str] = []
    for h in semantic_hits:
        slug = h.chunk.metadata.get("slug") or h.chunk.doc_id
        sem_slugs.append(slug)
        by_slug.setdefault(slug, _summary(h.chunk.metadata, slug))
    return [by_slug[s] for s in rrf_fuse([lex_slugs, sem_slugs]) if s in by_slug][:limit]
