import pytest

pytest.importorskip("docling")
pytestmark = pytest.mark.slow

from madosho.adapters.docling.chunker import DoclingHybridChunker
from madosho.adapters.docling.fastlane import PyPdfiumParser
from madosho.adapters.docling.parser import DoclingParser
from madosho.adapters.docling.router import RouterParser
from madosho.core.types import SourceFile
from madosho.testing.contracts import ParserContractTests


def sf(path):
    return SourceFile(path=str(path), mimetype="application/pdf", content_hash="x")


class TestDoclingParserContract(ParserContractTests):
    @pytest.fixture
    def parser(self):
        return DoclingParser.make()

    @pytest.fixture
    def sample_file(self, contract_pdf):
        return contract_pdf


class TestPyPdfiumParserContract(ParserContractTests):
    @pytest.fixture
    def parser(self):
        return PyPdfiumParser.make()

    @pytest.fixture
    def sample_file(self, contract_pdf):
        return contract_pdf


def test_parsers_attach_native_docling_document(contract_pdf):
    for parser in (DoclingParser.make(), PyPdfiumParser.make()):
        doc = parser.parse(sf(contract_pdf))
        assert doc.native is not None
        assert any("ninety days" in b.content for b in doc.blocks)


def test_hybrid_chunker_contextualizes_with_headings(contract_pdf):
    doc = DoclingParser.make().parse(sf(contract_pdf))
    chunks = DoclingHybridChunker.make().chunk(doc)
    assert chunks
    target = next(c for c in chunks if "ninety days" in c.text)
    assert target.doc_id == doc.doc_id and target.page == 1
    assert target.metadata["source"].endswith("contract_a.pdf")


def test_hybrid_chunker_requires_native():
    from madosho.core.errors import MadoshoError
    from madosho.core.types import Document
    bare = Document(doc_id="d", source=sf("x.pdf"), blocks=[])
    with pytest.raises(MadoshoError, match="native"):
        DoclingHybridChunker.make().chunk(bare)


def test_router_picks_fast_lane_for_text_layer(contract_pdf):
    router = RouterParser.make(fast_lane=True)
    doc = router.parse(sf(contract_pdf))
    assert doc.native is not None
    assert any("ninety days" in b.content for b in doc.blocks)


def test_parser_ocr_option_accepted():
    assert DoclingParser.make(ocr=True).options.ocr is True
    assert DoclingParser.make().options.ocr is False
    assert DoclingParser.make().options.ocr_engine == "tesseract"


def test_supports_office_web_text_formats_and_rejects_media_lanes():
    p = DoclingParser.make()
    # office / web / text / email / epub go through the docling structure lane
    for name in ("a.pdf", "a.docx", "a.pptx", "a.xlsx", "a.html", "a.md",
                 "a.txt", "a.csv", "a.adoc", "a.eml", "a.epub"):
        assert p.supports(sf(name)), name
    # without OCR images belong to the vision parser, audio needs ASR weights we
    # do not bundle, and .xml/.json are too ambiguous to claim -- all unsupported
    for name in ("a.png", "a.jpg", "a.mp3", "a.wav", "a.json", "a.xml", "a.bin"):
        assert not p.supports(sf(name)), name


def test_supports_images_only_when_ocr_enabled():
    ocr_on = DoclingParser.make(ocr=True)
    for name in ("scan.png", "scan.jpg", "scan.tiff", "scan.webp"):
        assert ocr_on.supports(sf(name)), name
    # audio/ambiguous formats stay out even with OCR on
    for name in ("a.mp3", "a.json", "a.xml"):
        assert not ocr_on.supports(sf(name)), name


class TestOcrEngineMapping:
    """make_ocr_options maps the engine name to docling's per-engine options
    class -- and fails with an INSTALL HINT (not a deep ImportError) when the
    engine's dependency is absent."""

    def test_tesseract_defaults_to_eng_and_parses_lang_csv(self):
        import shutil
        from madosho.adapters.docling.parser import make_ocr_options
        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary not installed")
        from docling.datamodel.pipeline_options import TesseractCliOcrOptions
        opts = make_ocr_options("tesseract", "", False)
        assert isinstance(opts, TesseractCliOcrOptions)
        # docling's own default lang list needs traineddata most installs lack;
        # ours must collapse to eng so the default engine works out of the box
        assert opts.lang == ["eng"]
        multi = make_ocr_options("tesseract", "eng, fra", True)
        assert multi.lang == ["eng", "fra"] and multi.force_full_page_ocr is True

    def test_rapidocr_maps_when_onnxruntime_present(self):
        pytest.importorskip("onnxruntime")
        from docling.datamodel.pipeline_options import RapidOcrOptions
        from madosho.adapters.docling.parser import make_ocr_options
        opts = make_ocr_options("rapidocr", "", False)
        assert isinstance(opts, RapidOcrOptions)

    def test_missing_engine_dep_names_the_fix(self):
        from importlib.util import find_spec
        from madosho.core.errors import MissingDependencyError
        from madosho.adapters.docling.parser import make_ocr_options
        if find_spec("easyocr") is not None:
            pytest.skip("easyocr installed; the missing-dep path is not reachable")
        with pytest.raises(MissingDependencyError, match="ocr-easyocr"):
            make_ocr_options("easyocr", "", False)


def test_router_forwards_ocr_options_to_structure_lane():
    router = RouterParser.make(ocr=True, ocr_engine="rapidocr", ocr_langs="english",
                               force_full_page_ocr=True)
    structure = router._structure.options
    assert structure.ocr is True
    assert structure.ocr_engine == "rapidocr"
    assert structure.ocr_langs == "english"
    assert structure.force_full_page_ocr is True
    # and the ocr option makes the router (via its structure lane) claim images
    assert router.supports(sf("scan.png"))
    assert not RouterParser.make().supports(sf("scan.png"))


class TestOcrEndToEnd:
    """Real OCR over a synthetic scan: an image-only PDF and a bare PNG, no
    text layer anywhere -- only a working engine can produce these blocks."""

    def _extracted(self, parser, path):
        doc = parser.parse(sf(path))
        joined = "".join(b.content for b in doc.blocks).upper().replace(" ", "")
        return joined

    def test_tesseract_reads_scanned_pdf_and_png(self, scanned_pdf, scan_png):
        import shutil
        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary not installed")
        p = DoclingParser.make(ocr=True, ocr_engine="tesseract")
        assert "NINETYDAYS" in self._extracted(p, scanned_pdf)
        assert "NINETYDAYS" in self._extracted(p, scan_png)

    def test_rapidocr_reads_scanned_pdf(self, scanned_pdf):
        pytest.importorskip("onnxruntime")
        p = DoclingParser.make(ocr=True, ocr_engine="rapidocr")
        assert "NINETYDAYS" in self._extracted(p, scanned_pdf)

    def test_router_ocrs_scanned_pdf_even_with_fast_lane(self, scanned_pdf):
        import shutil
        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary not installed")
        # the scan fails the text-layer probe, so the router must fall through
        # to the structure lane and OCR there -- fast_lane must not swallow it
        router = RouterParser.make(fast_lane=True, ocr=True)
        assert "NINETYDAYS" in self._extracted(router, scanned_pdf)

    def test_ocr_off_scanned_pdf_yields_no_text(self, scanned_pdf):
        # the counterfactual pinning why item 3 exists: without OCR a scan
        # parses "successfully" but produces zero text blocks
        doc = DoclingParser.make().parse(sf(scanned_pdf))
        assert not any(b.content.strip() for b in doc.blocks)


def test_parses_markdown_html_and_csv(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("# Heading\n\nThe termination clause requires ninety days notice.\n")
    html = tmp_path / "page.html"
    html.write_text("<h1>Title</h1><p>Hello</p><table><tr><td>a</td><td>b</td></tr></table>")
    csv = tmp_path / "rows.csv"
    csv.write_text("name,qty\napples,3\n")
    p = DoclingParser.make()
    for path, needle in ((md, "ninety days"), (html, "Hello"), (csv, "apples")):
        doc = p.parse(sf(path))
        assert doc.native is not None
        assert any(needle in b.content for b in doc.blocks), path.name


def test_router_routes_non_pdf_to_structure_lane(tmp_path):
    # even with the PDF-only fast lane opted in, a non-PDF must take the structure
    # (docling) lane instead of crashing the pypdfium fast lane
    md = tmp_path / "note.md"
    md.write_text("# H\n\nninety days notice clause.\n")
    doc = RouterParser.make(fast_lane=True).parse(sf(md))
    assert doc.native is not None
    assert any("ninety days" in b.content for b in doc.blocks)
