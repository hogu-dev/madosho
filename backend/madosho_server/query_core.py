from __future__ import annotations

from madosho.core.types import Hit, display_source
from madosho_server import llm
from madosho_server.provenance import origin_label

DEFAULT_TEMPLATE = (
    "You are a helpful assistant. Use the following retrieved context to answer "
    "the user's question. If the context is insufficient, say so.\n\n"
    "Context:\n{context}\n"
)


def serialize_pipeline_hits(pipeline_hits: list, origins=None) -> list[dict]:
    """Serialize PipelineHit objects (retrieval.multi_pipeline_query output) for
    the HTTP response. Citations carry document_id AND pipeline attribution
    (D14). `origins` maps document_id -> (origin, origin_meta); when a hit's
    document is 'generated', its provenance suffix is appended to the citation
    STRING (so it flows to agents/MCP/toolserver, which copy the string
    verbatim) and set as the structured `origin` field. Missing/None -> every
    doc treated as source (label empty, output unchanged)."""
    origins = origins or {}
    out = []
    for ph in pipeline_hits:
        h = ph.hit
        origin, meta = origins.get(ph.document_id, ("source", {}))
        suffix = origin_label(origin, meta)
        citation = f"{h.citation} {suffix}" if suffix else h.citation
        out.append({"text": h.text, "score": h.score, "page": h.chunk.page,
                    "citation": citation,
                    "source": display_source(h.chunk.metadata.get("source")),
                    "document_id": ph.document_id, "position": h.chunk.position,
                    "pipeline_id": ph.pipeline_id, "pipeline": ph.pipeline_name,
                    "origin": origin})
    return out


# Retained for the single-corpus generate() / direct-kernel path; not used by the
# multi-index HTTP handlers (which use serialize_pipeline_hits).
def serialize_hits(hits: list[Hit], doc_id_map: dict[str, int] | None = None) -> list[dict]:
    out = []
    for h in hits:
        row = {"text": h.text, "score": h.score, "page": h.chunk.page,
               "citation": h.citation, "source": display_source(h.chunk.metadata.get("source"))}
        if doc_id_map is not None:
            row["document_id"] = doc_id_map.get(h.chunk.doc_id)
            row["position"] = h.chunk.position
        out.append(row)
    return out


def render_context(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{i + 1}] ({h.citation})\n{h.text}"
                       for i, h in enumerate(hits))


def render_citations(hits: list[Hit]) -> str:
    if not hits:
        return ""
    lines = "\n".join(f"[{i + 1}] {h.citation}" for i, h in enumerate(hits))
    return f"\n\nSources:\n{lines}"


def augmented_messages(hits: list[Hit], user_messages: list[dict],
                       template: str | None = None) -> list[dict]:
    # str.replace (not .format) so stray braces in operator-supplied templates
    # or chunk text never raise.
    system = (template or DEFAULT_TEMPLATE).replace("{context}", render_context(hits))
    return [{"role": "system", "content": system}, *user_messages]


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def generate_from_hits(hits: list[Hit], user_messages: list[dict], provider: str,
                       model: str, settings, template: str | None = None,
                       stream: bool = False):
    """Augment pre-retrieved hits and call the provider. Returns (raw result, hits).
    Retrieval already happened (multi-index, in the API layer)."""
    messages = augmented_messages(hits, user_messages, template)
    # keyword `messages=` so `lambda **kw` test fakes accept the call too
    result = llm.complete(messages=messages, provider=provider, model=model,
                          settings=settings, stream=stream)
    return result, hits


def generate(corpus, user_messages: list[dict], provider: str, model: str,
             settings, template: str | None = None, stream: bool = False):
    """Single-corpus retrieve + augment + generate (kept for direct kernel use)."""
    hits = corpus.query(last_user_text(user_messages))
    return generate_from_hits(hits, user_messages, provider, model, settings,
                              template, stream)
