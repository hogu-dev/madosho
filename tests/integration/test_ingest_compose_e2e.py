# tests/integration/test_ingest_compose_e2e.py
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.slow
ROOT = Path(__file__).resolve().parents[2]


def _tiny_pdf(path: Path) -> None:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "The termination clause ends the agreement after thirty days.")
    pdf.output(str(path))


@pytest.fixture(scope="module")
def stack():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
    try:
        # wait for the control plane to answer /health (image build + model pull is slow)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            try:
                if httpx.get("http://127.0.0.1:8000/health", timeout=5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(5)
        else:
            pytest.fail("control plane did not become healthy in time")
        yield "http://127.0.0.1:8000"
    finally:
        # Dump service logs BEFORE tearing the stack down. pytest hides captured
        # output on success and surfaces it on failure — so when a nightly run
        # fails, the worker traceback (e.g. a missing ingest dependency) is right
        # there in the report instead of being destroyed by `down -v`.
        subprocess.run(["docker", "compose", "logs", "--tail", "80", "worker", "app"],
                       cwd=ROOT, check=False)
        subprocess.run(["docker", "compose", "down", "-v"], cwd=ROOT, check=False)


def test_upload_reaches_indexed(stack, tmp_path):
    base = stack
    r = httpx.post(f"{base}/corpora", json={"name": "contracts"}, timeout=30)
    assert r.status_code == 201
    corpus_id = r.json()["id"]

    pdf = tmp_path / "contract.pdf"
    _tiny_pdf(pdf)
    with open(pdf, "rb") as fh:
        r = httpx.post(f"{base}/corpora/{corpus_id}/documents",
                       files={"file": ("contract.pdf", fh, "application/pdf")}, timeout=60)
    assert r.status_code == 202
    doc_id = r.json()["id"]

    # poll until indexed (real docling parse + granite embed on CPU is slow)
    deadline = time.monotonic() + 900
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{base}/documents/{doc_id}", timeout=30).json()["status"]
        if status in ("indexed", "failed"):
            break
        time.sleep(5)
    assert status == "indexed", f"document ended in status {status!r}"
