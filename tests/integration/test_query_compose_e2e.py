# tests/integration/test_query_compose_e2e.py
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.slow
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def stack():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    try:
        subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
        # Wait for BOTH planes to answer /health under a shared deadline.
        # Image build + model pull can be slow; 1200 s is generous but mirrors B.
        deadline = time.monotonic() + 1200

        for url, label in [
            ("http://127.0.0.1:8000/health", "control plane"),
            ("http://127.0.0.1:8001/health", "query plane"),
        ]:
            while time.monotonic() < deadline:
                try:
                    if httpx.get(url, timeout=5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(5)
            else:
                pytest.fail(f"{label} did not become healthy in time")

        yield {
            "control": "http://127.0.0.1:8000",
            "query": "http://127.0.0.1:8001",
        }
    finally:
        # Dump service logs BEFORE tearing the stack down.  Including 'query'
        # means query-plane failures (retrieval errors, bad config) appear in
        # the report without the operator having to re-spin the stack.
        subprocess.run(
            ["docker", "compose", "logs", "--tail", "80", "worker", "app", "query"],
            cwd=ROOT,
            check=False,
        )
        subprocess.run(["docker", "compose", "down", "-v"], cwd=ROOT, check=False)


def test_upload_indexed_then_query(stack, contract_pdf):
    control = stack["control"]
    query = stack["query"]

    # --- create corpus ---
    r = httpx.post(f"{control}/corpora", json={"name": "e2e"}, timeout=30)
    assert r.status_code == 201
    corpus_id = r.json()["id"]

    # --- upload document ---
    with open(contract_pdf, "rb") as fh:
        r = httpx.post(
            f"{control}/corpora/{corpus_id}/documents",
            files={"file": ("contract_a.pdf", fh, "application/pdf")},
            timeout=60,
        )
    assert r.status_code == 202
    doc_id = r.json()["id"]

    # --- poll until indexed (docling + granite embed on CPU is slow) ---
    deadline = time.monotonic() + 900
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{control}/documents/{doc_id}", timeout=30).json()["status"]
        if status in ("indexed", "failed"):
            break
        time.sleep(5)
    else:
        pytest.fail(f"document did not reach indexed within timeout; last status: {status!r}")
    assert status == "indexed", f"document ended in status {status!r}"

    # --- query the query plane (retrieval only; generation covered by Task 14) ---
    r = httpx.post(
        f"{query}/query",
        json={"corpus": "e2e", "prompt": "termination notice period"},
        timeout=60,
    )
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert hits, "query returned no hits"
    assert any(
        "termination" in h["text"].lower() or "ninety" in h["text"].lower()
        for h in hits
    ), f"expected termination/ninety in returned chunks; got: {[h['text'][:80] for h in hits]}"
