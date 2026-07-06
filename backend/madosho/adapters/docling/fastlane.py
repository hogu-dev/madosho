from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Document, SourceFile

from madosho.adapters.docling.parser import PDF_SUFFIXES, docling_to_document

# US-Letter point dimensions; the fast lane carries no real layout, but
# docling-core's add_page requires a non-null Size (drift from the plan's
# size=None, which the installed docling-core 2.81.0 rejects).
DEFAULT_PAGE_SIZE = (612.0, 792.0)


def pdf_page_texts(path: str) -> list[str]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return [page.get_textpage().get_text_bounded() for page in pdf]
    finally:
        pdf.close()


class PyPdfiumParser(ComponentBase):
    """Fast lane: raw pypdfium2 text extraction wrapped in a minimal
    DoclingDocument so the hybrid chunker works unchanged. No layout, no tables."""

    META = ComponentMeta(
        name="pypdfium2", kind=ComponentKind.PARSER, version="0.1.0",
        license="Apache-2.0 OR BSD-3-Clause", org="pypdfium2-team", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="docling")

    class Options(BaseModel):
        pass

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def supports(self, file: SourceFile) -> bool:
        return Path(file.path).suffix.lower() in PDF_SUFFIXES

    def parse(self, file: SourceFile) -> Document:
        from docling_core.types.doc import (
            BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size,
        )

        dl_doc = DoclingDocument(name=Path(file.path).stem)
        size = Size(width=DEFAULT_PAGE_SIZE[0], height=DEFAULT_PAGE_SIZE[1])
        for page_no, text in enumerate(pdf_page_texts(file.path), start=1):
            dl_doc.add_page(page_no=page_no, size=size)
            for para in (p.strip() for p in text.split("\n\n")):
                if para:
                    dl_doc.add_text(
                        label=DocItemLabel.TEXT, text=para,
                        prov=ProvenanceItem(page_no=page_no, charspan=(0, len(para)),
                                            bbox=BoundingBox(l=0, t=0, r=0, b=0)))
        return docling_to_document(dl_doc, file)
