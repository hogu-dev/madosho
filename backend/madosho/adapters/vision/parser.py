from __future__ import annotations

import hashlib
import io
from pathlib import Path

from pydantic import BaseModel, Field

from madosho.core.errors import ConfigError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Block, BlockKind, Document, Provenance, SourceFile

# Mimetypes/suffixes the vision lane can read. PDFs are rasterized page by page;
# a directly-uploaded image is treated as a single page. Uploads sometimes arrive
# as application/octet-stream, so suffix is the fallback signal.
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
PDF_MIMETYPES = {"application/pdf"}
IMAGE_MIMETYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp",
                   "image/gif", "image/tiff", "image/bmp"}

DEFAULT_PROMPT = (
    "Transcribe this page image faithfully to text. Preserve the reading order and "
    "table structure (render tables as GitHub-flavored Markdown). Output only the "
    "transcription, with no commentary or preamble."
)


def _doc_id_for(file: SourceFile) -> str:
    # Same scheme as the docling parser's doc_id_for, replicated here so the vision
    # adapter does not import the docling module (which pulls heavy deps at import).
    return hashlib.sha256(file.path.encode()).hexdigest()[:16]


def render_pdf_pages(path: str, *, dpi: int, max_pages: int,
                     logger=None) -> list[tuple[int, bytes]]:
    """Rasterize a PDF's pages to PNG bytes (1-indexed) with pypdfium2.

    dpi drives the render scale (72 dpi == 1.0). Renders at most max_pages pages and
    warns (via `logger`) when the document is longer, so a truncated transcription
    is never silent. The server's extraction lane has a near-identical helper; this
    kernel-side copy keeps the parser from depending on the service layer.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        total = len(pdf)
        n = min(total, max_pages)
        if total > max_pages and logger is not None:
            logger.warning("vision parser: %s has %d pages; transcribing the first "
                           "%d (max_pages=%d)", path, total, n, max_pages)
        out: list[tuple[int, bytes]] = []
        scale = dpi / 72.0
        for i in range(n):
            pil = pdf[i].render(scale=scale).to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            out.append((i + 1, buf.getvalue()))
        return out
    finally:
        pdf.close()


def image_to_png(data: bytes) -> bytes:
    """Normalize arbitrary image bytes to PNG so the VisionClient contract is one
    type. A re-encode also rescues formats a provider might reject (tiff/bmp)."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class VisionParser(ComponentBase):
    """Parser that transcribes a document by *looking at it*: each PDF page is
    rendered to an image and handed to a vision LLM (or a directly-uploaded image
    is sent as-is). Built for scans, photographed pages, and layouts where the
    embedded text is missing or garbled -- exactly the cases the text-extraction
    parsers (docling, pypdfium2) cannot help with.

    Why this design (teaching notes):

    - **Vision rides a separate runtime seam.** A parser is a *kernel* component,
      but the kernel's `runtime.llm` is text-only (``prompt -> str``). Page images
      cannot go through it, so this parser calls ``runtime.vision`` -- a parallel
      multimodal seam the service injects from the configured vision endpoint. The
      kernel never names a provider; the base64/HTTP details stay service-side.

    - **One block per page.** Each page's transcription becomes a single TEXT block
      tagged with its page number. The model already emits readable prose/Markdown,
      so downstream the *text* chunkers (recursive-text, contextual, semantic) split
      it like any other document. It does NOT pair with docling-hybrid, which needs
      a native DoclingDocument this parser never produces.

    - **Fail loud, never silently empty.** If no vision client is wired in, parsing
      raises ConfigError rather than returning an empty document that would look
      like a successful-but-blank ingest.
    """

    META = ComponentMeta(
        name="vision", kind=ComponentKind.PARSER, version="0.1.0",
        license="Apache-2.0", org="madosho", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="docling")

    class Options(BaseModel):
        # Rasterization controls (PDF lane). Higher dpi = sharper page but bigger
        # images and more tokens; 150 is a readable default.
        dpi: int = Field(default=150, gt=0)
        # Cap pages so a pathologically long PDF cannot run up an unbounded vision
        # bill / context overflow. Pages past the cap are dropped (logged).
        max_pages: int = Field(default=50, gt=0)
        prompt: str = DEFAULT_PROMPT
        # Which configured vision endpoint to transcribe with. The kernel itself
        # ignores this (it calls whatever runtime.vision the host injected); the
        # SERVICE reads it from the recipe to pick which registry endpoint to bind
        # as runtime.vision for this build. None -> the host's vision-default.
        vision_endpoint: str | None = None

    def __init__(self, options: Options | None = None,
                 runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def supports(self, file: SourceFile) -> bool:
        mt = (file.mimetype or "").lower()
        if mt in PDF_MIMETYPES or mt in IMAGE_MIMETYPES:
            return True
        # octet-stream / unknown mimetype: fall back to the file suffix
        return Path(file.path).suffix.lower() in (PDF_SUFFIXES | IMAGE_SUFFIXES)

    def parse(self, file: SourceFile) -> Document:
        vision = getattr(self.runtime, "vision", None)
        if vision is None:
            raise ConfigError(
                "parser 'vision' needs an index-time vision LLM, but none is "
                "configured (runtime.vision is None). Configure a vision-capable "
                "LLM endpoint for the ingest lane, or pick a text-extraction parser.")

        blocks: list[Block] = []
        for page_no, png in self._page_images(file):
            text = (vision(self.options.prompt, [png]) or "").strip()
            if text:
                blocks.append(Block(
                    kind=BlockKind.TEXT, content=text,
                    provenance=Provenance(source=file.path, page=page_no)))
        return Document(doc_id=_doc_id_for(file), source=file, blocks=blocks)

    def _page_images(self, file: SourceFile) -> list[tuple[int, bytes]]:
        mt = (file.mimetype or "").lower()
        suffix = Path(file.path).suffix.lower()
        if mt in PDF_MIMETYPES or suffix in PDF_SUFFIXES:
            logger = self.runtime.logger if self.runtime is not None else None
            return render_pdf_pages(file.path, dpi=self.options.dpi,
                                    max_pages=self.options.max_pages, logger=logger)
        # single image -> one page, normalized to PNG
        return [(1, image_to_png(Path(file.path).read_bytes()))]
