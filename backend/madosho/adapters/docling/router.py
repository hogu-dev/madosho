from __future__ import annotations

from pydantic import BaseModel

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Document, SourceFile

from madosho.adapters.docling.fastlane import PyPdfiumParser, pdf_page_texts
from madosho.adapters.docling.parser import DoclingParser, OcrEngineName

MIN_CHARS_PER_PAGE = 32   # below this we assume no usable text layer


class RouterParser(ComponentBase):
    """Composite parser. PDFs pick a lane: fast (pypdfium2) for text-layer PDFs,
    else structure (Docling); pages without a text layer route to the structure
    lane. Non-PDF documents (docx/html/md/... -- see DoclingParser.supports) always
    take the structure lane. The ocr options pass through to the structure lane,
    so with ocr on a scanned PDF that fails the text-layer probe gets real OCR
    instead of coming back empty. (VLM transcription is the separate `vision`
    parser.)"""

    META = ComponentMeta(
        name="router", kind=ComponentKind.PARSER, version="0.1.0",
        license="Apache-2.0", org="madosho", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="docling")

    class Options(BaseModel):
        fast_lane: bool = False   # opt-in: route text-layer PDFs to pypdfium2
        # OCR fields mirror DoclingParser.Options and are forwarded verbatim
        # to the structure lane; see that class for per-field docs.
        ocr: bool = False
        ocr_engine: OcrEngineName = "tesseract"
        ocr_langs: str = ""
        force_full_page_ocr: bool = False

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime
        self._fast = PyPdfiumParser(runtime=runtime)
        self._structure = DoclingParser(
            options=DoclingParser.Options(
                **self.options.model_dump(exclude={"fast_lane"})),
            runtime=runtime)

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def supports(self, file: SourceFile) -> bool:
        return self._structure.supports(file)

    def _has_text_layer(self, file: SourceFile) -> bool:
        try:
            pages = pdf_page_texts(file.path)
        except Exception:
            return False
        return bool(pages) and all(len(t.strip()) >= MIN_CHARS_PER_PAGE for t in pages)

    def parse(self, file: SourceFile) -> Document:
        # The fast lane is pypdfium (PDF-only); non-PDF inputs (docx/html/md/...)
        # always take the structure lane, which docling parses natively.
        if (self.options.fast_lane and self._fast.supports(file)
                and self._has_text_layer(file)):
            return self._fast.parse(file)
        return self._structure.parse(file)
