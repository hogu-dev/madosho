from __future__ import annotations

from pydantic import BaseModel

from madosho.core.errors import MadoshoError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Chunk, Document

from madosho.adapters.docling.parser import normalize_ws

# HybridChunker import is deferred to _get_chunker() — see lazy init below


class DoclingHybridChunker(ComponentBase):
    """Docling HybridChunker over the parser's native DoclingDocument.
    Heading path becomes the context prefix (spec §12: LLM contextual
    augmentation is a later, separate feature)."""

    META = ComponentMeta(
        name="docling-hybrid", kind=ComponentKind.CHUNKER, version="0.1.0",
        license="MIT", org="IBM / LF AI & Data", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="docling")

    class Options(BaseModel):
        max_tokens: int | None = None   # None -> HybridChunker default

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime
        self._chunker = None   # lazy: builds a tokenizer

    def _get_chunker(self):
        if self._chunker is None:
            from docling.chunking import HybridChunker

            kwargs = {}
            if self.options.max_tokens is not None:
                kwargs["max_tokens"] = self.options.max_tokens
            self._chunker = HybridChunker(**kwargs)
        return self._chunker

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    @property
    def native(self):
        # NOTE: reading .native builds the heavy converter/tokenizer on first access
        return self._get_chunker()

    def chunk(self, doc: Document) -> list[Chunk]:
        if doc.native is None:
            raise MadoshoError(
                f"chunker 'docling-hybrid' needs the parser's native DoclingDocument "
                f"on Document.native; parser for {doc.source.path} did not provide one")
        chunks: list[Chunk] = []
        for i, dl_chunk in enumerate(self._get_chunker().chunk(dl_doc=doc.native)):
            headings = list(getattr(dl_chunk.meta, "headings", None) or [])
            page = None
            items = getattr(dl_chunk.meta, "doc_items", None) or []
            if items and getattr(items[0], "prov", None):
                page = items[0].prov[0].page_no
            chunks.append(Chunk(
                id=f"{doc.doc_id}-{i:04d}", doc_id=doc.doc_id,
                text=normalize_ws(dl_chunk.text),
                context_prefix=" / ".join(headings), position=i, page=page,
                metadata={"source": doc.source.path}))
        return chunks
