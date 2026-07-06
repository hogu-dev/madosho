import io
import logging
from pathlib import Path

import pytest

from madosho.adapters.vision import parser as vision_mod
from madosho.adapters.vision.parser import VisionParser
from madosho.core.errors import ConfigError
from madosho.core.meta import ComponentKind
from madosho.core.protocols import RuntimeContext
from madosho.core.registry import Registry
from madosho.core.types import SourceFile
from madosho.testing.contracts import ParserContractTests


class FakeVision:
    """A callable (prompt, images) -> str standing in for runtime.vision. Records
    the calls so tests can assert what the parser sent per page."""

    def __init__(self, reply="TRANSCRIBED PAGE"):
        self.reply = reply
        self.calls: list[tuple[str, list[bytes]]] = []

    def __call__(self, prompt: str, images: list[bytes]) -> str:
        self.calls.append((prompt, images))
        # echo a per-page marker so multi-page output is distinguishable
        return f"{self.reply} ({len(self.calls)})"


def _runtime(vision=None) -> RuntimeContext:
    return RuntimeContext(
        corpus="test", data_dir=Path("/tmp/madosho-vision"), cache_dir=None,
        logger=logging.getLogger("madosho.test"), vision=vision)


def _png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_file(tmp_path) -> Path:
    p = tmp_path / "page.png"
    p.write_bytes(_png_bytes())
    return p


class TestVisionParserContract(ParserContractTests):
    """Drive the shared parser contract over the image lane (no real PDF needed)."""

    @pytest.fixture
    def parser(self):
        return VisionParser(runtime=_runtime(vision=FakeVision()))

    @pytest.fixture
    def sample_file(self, png_file):
        return png_file


def _sf(path, mimetype="application/octet-stream"):
    return SourceFile(path=str(path), mimetype=mimetype, content_hash="x")


def test_registered_and_resolvable():
    reg = Registry()
    assert "vision" in reg.names(ComponentKind.PARSER)
    assert reg.load_class(ComponentKind.PARSER, "vision") is VisionParser


def test_supports_pdf_and_images_rejects_text():
    p = VisionParser(runtime=_runtime(vision=FakeVision()))
    assert p.supports(_sf("doc.pdf", "application/pdf"))
    assert p.supports(_sf("scan.png", "image/png"))
    assert p.supports(_sf("photo.jpg", "image/jpeg"))
    # octet-stream upload: decided by suffix
    assert p.supports(_sf("doc.pdf"))
    assert p.supports(_sf("scan.PNG"))
    assert not p.supports(_sf("notes.txt", "text/plain"))
    assert not p.supports(_sf("notes.txt"))


def test_missing_vision_raises_clearly(png_file):
    p = VisionParser(runtime=_runtime(vision=None))
    with pytest.raises(ConfigError) as exc:
        p.parse(_sf(png_file, "image/png"))
    assert "vision" in str(exc.value).lower()


def test_image_lane_one_page_block(png_file):
    vision = FakeVision(reply="HELLO")
    doc = VisionParser(runtime=_runtime(vision=vision)).parse(_sf(png_file, "image/png"))
    assert len(doc.blocks) == 1
    assert doc.blocks[0].content == "HELLO (1)"
    assert doc.blocks[0].provenance.page == 1
    # the parser sent exactly one image (normalized to PNG) with the prompt
    assert len(vision.calls) == 1
    prompt, images = vision.calls[0]
    assert "Transcribe" in prompt
    assert len(images) == 1 and images[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_pdf_lane_one_block_per_page(monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")           # never really opened (render is faked)
    fake_pages = [(1, b"png-1"), (2, b"png-2"), (3, b"png-3")]
    monkeypatch.setattr(vision_mod, "render_pdf_pages",
                        lambda path, **kw: fake_pages)
    vision = FakeVision()
    doc = VisionParser(runtime=_runtime(vision=vision)).parse(_sf(pdf, "application/pdf"))
    assert [b.provenance.page for b in doc.blocks] == [1, 2, 3]
    assert len(vision.calls) == 3
    # each page image was forwarded straight through
    assert [imgs[0] for _, imgs in vision.calls] == [b"png-1", b"png-2", b"png-3"]


def test_empty_transcription_skips_block(monkeypatch, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(vision_mod, "render_pdf_pages",
                        lambda path, **kw: [(1, b"a"), (2, b"b")])

    class BlankSecond(FakeVision):
        def __call__(self, prompt, images):
            self.calls.append((prompt, images))
            return "page one" if len(self.calls) == 1 else "   "

    doc = VisionParser(runtime=_runtime(vision=BlankSecond())).parse(_sf(pdf, "application/pdf"))
    assert [b.provenance.page for b in doc.blocks] == [1]   # blank page 2 dropped


def test_vision_endpoint_option_is_accepted():
    # service-only field: must be a valid kernel option (round-trips through config)
    p = VisionParser.make(vision_endpoint="my-vision-gpu", dpi=200)
    assert p.options.vision_endpoint == "my-vision-gpu"
    assert p.options.dpi == 200
