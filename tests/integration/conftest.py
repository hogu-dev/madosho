from pathlib import Path

import pytest


def make_pdf(path: Path, paragraphs: list[str], title: str | None = None) -> Path:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    # fpdf2 2.8.7 defaults multi_cell new_x to RIGHT, leaving the cursor at the
    # right margin; the next multi_cell(0, ...) then has zero width and raises
    # "Not enough horizontal space". Pin new_x/new_y so the cursor returns to the
    # left margin on the next line (the pre-2.x default the plan assumed).
    nl = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf = FPDF()
    pdf.add_page()
    if title:
        pdf.set_font("helvetica", "B", 16)
        pdf.multi_cell(0, 10, title, **nl)
    pdf.set_font("helvetica", size=12)
    for p in paragraphs:
        pdf.multi_cell(0, 8, p, **nl)
        pdf.ln(4)
    pdf.output(str(path))
    return path


def make_scan_image(path: Path, text: str) -> Path:
    """Render text into a letter-sized bitmap -- a stand-in for a scanner's
    output. Three quirks matter to OCR engines: glyphs must be tall (~30px, so
    draw with PIL's tiny built-in font and upscale 2x -- keeps the fixture
    font-free), the page needs several lines (tesseract's script-detection
    pass refuses pages with "too few characters"), and the file needs DPI
    metadata (tesseract warns "invalid resolution 0 dpi" without it)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (850, 1100), "white")
    draw = ImageDraw.Draw(img)
    for i in range(6):
        draw.text((60, 80 + i * 60), text, fill="black")
    img.resize((1700, 2200)).save(path, dpi=(200, 200))
    return path


def make_scanned_pdf(path: Path, tmp_path: Path, text: str) -> Path:
    """An image-only PDF (no text layer), like a scanner produces: the rendered
    bitmap is embedded as a full-width picture on an otherwise empty page."""
    from fpdf import FPDF

    png = make_scan_image(tmp_path / "_scan_src.png", text)
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(png), x=10, y=10, w=190)
    pdf.output(str(path))
    return path


@pytest.fixture
def scan_png(tmp_path):
    return make_scan_image(tmp_path / "scan.png", "NINETY DAYS NOTICE")


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_scanned_pdf(tmp_path / "scan.pdf", tmp_path, "NINETY DAYS NOTICE")


@pytest.fixture
def contract_pdf(tmp_path):
    return make_pdf(tmp_path / "contract_a.pdf", title="Service Agreement", paragraphs=[
        "1. Term. This agreement runs for two years from the effective date.",
        "2. Termination. The termination clause requires ninety days written notice "
        "before the agreement may be ended by either party.",
        "3. Payment. Invoices are payable within thirty days of receipt.",
    ])
