from __future__ import annotations

import hashlib
import os
import re
import shutil
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from madosho.core.errors import MissingDependencyError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import (
    Block, BlockKind, Document, Provenance, SourceFile,
)

PDF_SUFFIXES = {".pdf"}   # the fast (pypdfium) lane and PDF-only routing use this

# The docling structure lane parses far more than PDF. We advertise the docling
# input formats that need NO extra models: office (docx/pptx/xlsx), web (html),
# markup/text (md, txt, asciidoc), csv, email (eml), epub, latex -- derived live
# from docling's own registry so the set tracks whatever docling version is
# installed. Deliberately EXCLUDED from this always-on set: `image` (needs an
# OCR engine -> accepted only when the ocr option is on, see supports(); VLM
# transcription is the vision parser's lane) and `audio`/`vtt` (needs ASR
# weights we do not bundle). Ambiguous .xml/.json are left out so we never grab
# arbitrary files as documents.
_TEXT_LANE_FORMATS = (
    "PDF", "DOCX", "PPTX", "XLSX", "HTML", "MD", "CSV", "ASCIIDOC",
    "EMAIL", "EPUB", "LATEX",
)
_supported_suffixes: frozenset[str] | None = None
_image_suffixes: frozenset[str] | None = None


def supported_suffixes() -> frozenset[str]:
    """Suffixes the docling parser accepts, derived once from docling's registry.
    Lazy so importing this module stays cheap (docling loads at ingest anyway)."""
    global _supported_suffixes
    if _supported_suffixes is None:
        from docling.datamodel.base_models import FormatToExtensions, InputFormat
        keep = {getattr(InputFormat, name, None) for name in _TEXT_LANE_FORMATS}
        keep.discard(None)
        _supported_suffixes = frozenset(
            "." + ext.lower() for fmt in keep for ext in FormatToExtensions.get(fmt, ()))
    return _supported_suffixes


def image_suffixes() -> frozenset[str]:
    """Image suffixes (png/jpg/tiff/...) the OCR-enabled parser additionally
    accepts, derived from docling's registry like supported_suffixes()."""
    global _image_suffixes
    if _image_suffixes is None:
        from docling.datamodel.base_models import FormatToExtensions, InputFormat
        _image_suffixes = frozenset(
            "." + ext.lower() for ext in FormatToExtensions.get(InputFormat.IMAGE, ()))
    return _image_suffixes


OcrEngineName = Literal["tesseract", "rapidocr", "easyocr"]


def make_ocr_options(engine: OcrEngineName, langs: str, force_full_page: bool):
    """Map an engine name to docling's per-engine OcrOptions.

    Each engine has its OWN language-code vocabulary (tesseract "eng", easyocr
    "en", rapidocr model names), so `langs` is passed through verbatim as a
    comma-separated list rather than translated; empty means the engine default.
    A missing engine dependency fails HERE with an install hint instead of a
    bare ImportError from deep inside docling at convert time.
    """
    lang_list = [t.strip() for t in langs.split(",") if t.strip()]
    if engine == "tesseract":
        from docling.datamodel.pipeline_options import TesseractCliOcrOptions
        opts = TesseractCliOcrOptions()
        if shutil.which(opts.tesseract_cmd) is None:
            raise MissingDependencyError(
                "OCR engine 'tesseract' needs the tesseract binary. Fix: "
                "apt-get install tesseract-ocr (the madosho image ships it)")
        # docling's default lang list (fra/deu/spa/eng) requires traineddata
        # files most installs don't have; Debian's tesseract-ocr package ships
        # only eng. Default to eng so the engine works out of the box.
        opts.lang = lang_list or ["eng"]
    elif engine == "rapidocr":
        if find_spec("onnxruntime") is None:
            raise MissingDependencyError(
                "OCR engine 'rapidocr' needs onnxruntime (the rapidocr package "
                "itself ships with docling). Fix: pip install onnxruntime")
        from docling.datamodel.pipeline_options import RapidOcrOptions
        # rapidocr's bundled PP-OCR models read Chinese AND Latin text; its
        # default lang selection is fine for English documents.
        opts = RapidOcrOptions(**({"lang": lang_list} if lang_list else {}))
    else:
        if find_spec("easyocr") is None:
            raise MissingDependencyError(
                "OCR engine 'easyocr' is not installed (kept out of the default "
                "image for size). Fix: pip install madosho[ocr-easyocr], or run "
                "the compose.ocr.yaml overlay")
        from docling.datamodel.pipeline_options import EasyOcrOptions
        opts = EasyOcrOptions(lang=lang_list or ["en"])
        # In containers the default model dir (~/.EasyOCR) is ephemeral; the
        # overlay points this at the shared /models volume so the ~100MB
        # download survives container recreation. No weights are baked anywhere.
        model_dir = os.environ.get("MADOSHO_EASYOCR_MODELS")
        if model_dir:
            opts.model_storage_directory = model_dir
    opts.force_full_page_ocr = force_full_page
    return opts

# Docling reconstructs word spacing from glyph bbox positions, which on
# justified / fpdf-generated PDFs yields runs of multiple spaces ("ninety  days").
# Those gaps carry no meaning, so we collapse horizontal whitespace runs to a
# single space (newlines preserved as soft paragraph separators) before the text
# reaches blocks and chunks. Without this, exact-phrase matching breaks downstream.
_WS_RUN = re.compile(r"[^\S\n]+")


def normalize_ws(text: str) -> str:
    return "\n".join(_WS_RUN.sub(" ", line).strip() for line in text.split("\n")).strip()


def doc_id_for(file: SourceFile) -> str:
    return hashlib.sha256(file.path.encode()).hexdigest()[:16]


def docling_to_document(dl_doc, file: SourceFile) -> Document:
    """Map a DoclingDocument to our Document, keeping the native object attached."""
    from docling_core.types.doc import DocItemLabel, TableItem, TextItem

    blocks: list[Block] = []
    for item, _level in dl_doc.iterate_items():
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        prov = Provenance(source=file.path, page=page)
        if isinstance(item, TableItem):
            blocks.append(Block(kind=BlockKind.TABLE,
                                content=item.export_to_markdown(doc=dl_doc),
                                provenance=prov))
        elif isinstance(item, TextItem) and item.text.strip():
            kind = (BlockKind.HEADING
                    if item.label in (DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER)
                    else BlockKind.TEXT)
            blocks.append(Block(kind=kind, content=normalize_ws(item.text), provenance=prov))
    return Document(doc_id=doc_id_for(file), source=file, blocks=blocks, native=dl_doc)


class DoclingParser(ComponentBase):
    """Structure lane. For PDFs this runs the full Docling pipeline (layout +
    TableFormer); for office/web/text formats (docx, pptx, xlsx, html, md, txt,
    csv, asciidoc, eml, epub, latex) docling uses its format-specific backends.
    With ocr=true, scanned PDFs and bare images (png/jpg/tiff/...) are read by
    the selected OCR engine (tesseract default; rapidocr; easyocr via overlay) --
    the classical alternative to the vision parser's VLM transcription.
    See supported_suffixes() / image_suffixes() for the exact sets (audio stays
    excluded: ASR needs weights we do not bundle)."""

    META = ComponentMeta(
        name="docling", kind=ComponentKind.PARSER, version="0.1.0",
        license="MIT", org="IBM / LF AI & Data", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="docling")

    class Options(BaseModel):
        ocr: bool = False   # default off: text-layer extraction is fast + CPU-safe
        # Engine used when ocr=true. tesseract = CPU, in the default image;
        # rapidocr = PP-OCR via onnxruntime (ships with docling, CN-developed
        # models -- see docs/COMPLIANCE.md); easyocr = CPU/GPU, opt-in overlay.
        ocr_engine: OcrEngineName = "tesseract"
        # Comma-separated language codes in the CHOSEN ENGINE's vocabulary
        # (tesseract "eng,fra", easyocr "en,fr"); empty = engine default.
        ocr_langs: str = ""
        # Re-OCR whole pages even where a text layer exists -- for PDFs whose
        # embedded text is garbage (bad scanner OCR baked into the file).
        force_full_page_ocr: bool = False

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime
        self._converter = None   # lazy: building it loads models

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def _get_converter(self):
        if self._converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import (
                DocumentConverter, ImageFormatOption, PdfFormatOption,
            )

            # Structure lane = layout + TableFormer. do_ocr defaults True in
            # docling 2.101.0 (with an engine auto-pick), so we set it
            # explicitly either way: off = text-layer extraction only; on = the
            # user-selected engine, resolved in make_ocr_options. Bare images
            # ride the same pipeline options -- docling routes them through its
            # PDF pipeline, so an OCR'd scan.png behaves like a one-page scan.pdf.
            opts = PdfPipelineOptions()
            opts.do_ocr = self.options.ocr
            if self.options.ocr:
                opts.ocr_options = make_ocr_options(
                    self.options.ocr_engine, self.options.ocr_langs,
                    self.options.force_full_page_ocr)
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts),
                })
        return self._converter

    @property
    def native(self):
        # NOTE: reading .native builds the heavy converter/tokenizer on first access
        return self._get_converter()

    def supports(self, file: SourceFile) -> bool:
        # Bare images (scan.png) are only claimable when OCR is on -- without an
        # engine there is no text to extract, and the vision parser owns that lane.
        suffix = Path(file.path).suffix.lower()
        return (suffix in supported_suffixes()
                or (self.options.ocr and suffix in image_suffixes()))

    def parse(self, file: SourceFile) -> Document:
        result = self._get_converter().convert(file.path)
        return docling_to_document(result.document, file)
