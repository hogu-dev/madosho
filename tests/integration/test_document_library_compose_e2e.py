"""Slow: needs the compose stack up. Like the pipelines e2e, this does NOT need a real
LLM provider - it exercises the document-centric library + membership surface
and single-document retrieval. Gated by docker presence; deselected by default
via the `slow` marker (addopts = "-m 'not slow'").

Run live:  .venv/bin/python -m pytest tests/integration/test_document_library_compose_e2e.py -m slow -q
"""
import shutil
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.slow
ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]

ALT_PARSER = "pypdfium2"   # second recipe axis, no extra models (mirrors test_g)


@pytest.fixture(scope="module")
def stack():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    try:
        subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
        deadline = time.monotonic() + 1200
        for url, label in [("http://127.0.0.1:8000/health", "control plane"),
                           ("http://127.0.0.1:8001/health", "query plane")]:
            while time.monotonic() < deadline:
                try:
                    if httpx.get(url, timeout=5).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(5)
            else:
                pytest.fail(f"{label} did not become healthy in time")
        yield {"control": "http://127.0.0.1:8000", "query": "http://127.0.0.1:8001"}
    finally:
        subprocess.run(["docker", "compose", "logs", "--tail", "80", "worker", "app", "query"],
                       cwd=ROOT, check=False)
        subprocess.run(["docker", "compose", "down", "-v"], cwd=ROOT, check=False)


def _wait_indexed(control: str, doc_id: int, timeout: int = 900) -> str:
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{control}/documents/{doc_id}", timeout=30).json()["status"]
        if status in ("indexed", "failed"):
            return status
        time.sleep(5)
    pytest.fail(f"document {doc_id} did not index within {timeout}s; last: {status!r}")


def test_document_centric_library_e2e(stack, contract_pdf):
    control, query = stack["control"], stack["query"]

    # Proof 1: library upload (POST /documents) with a chosen recipe -> indexed once.
    with open(contract_pdf, "rb") as fh:
        r = httpx.post(f"{control}/documents",
                       files={"file": ("contract.pdf", fh, "application/pdf")},
                       data={"parser": ALT_PARSER}, timeout=60)
    assert r.status_code == 202, f"library upload failed: {r.status_code} {r.text}"
    did = r.json()["id"]
    assert _wait_indexed(control, did) == "indexed"

    # Proof 2: GET /documents shows the library doc, no corpora yet, rating present.
    lib = httpx.get(f"{control}/documents", timeout=30).json()
    row = next(d for d in lib if d["id"] == did)
    assert row["corpora"] == []
    # rating is best-effort: rate_document runs non-fatally AFTER status flips to
    # "indexed" (tasks.ingest_document), so an indexed doc may have rating=None.
    # Assert the field is present, not that it is populated (matches the unit test).
    assert "rating" in row

    # Proof 3: add to a corpus (membership only) -> in-corpora list, still ONE doc.
    cid = httpx.post(f"{control}/corpora", json={"name": "e2e-h"}, timeout=30).json()["id"]
    r = httpx.post(f"{control}/corpora/{cid}/documents/{did}", timeout=30)
    assert r.status_code == 200
    detail = httpx.get(f"{control}/documents/{did}", timeout=30).json()
    assert [c["name"] for c in detail["corpora"]] == ["e2e-h"]
    assert detail["status"] == "indexed"                 # NOT re-indexed

    # Proof 4: single-document query (H11) returns hits attributed to the doc's pipeline.
    r = httpx.post(f"{query}/query",
                   json={"document_id": did,
                         "prompt": "What is the termination notice period?"},
                   timeout=60)
    assert r.status_code == 200, f"single-doc query failed: {r.status_code} {r.text}"
    hits = r.json().get("hits", [])
    assert hits and all(h.get("pipeline") for h in hits)

    # Proof 5: remove membership -> in-corpora empty, doc still in the library.
    assert httpx.request("DELETE", f"{control}/corpora/{cid}/documents/{did}",
                         timeout=30).status_code == 204
    detail = httpx.get(f"{control}/documents/{did}", timeout=30).json()
    assert detail["corpora"] == []
    lib = httpx.get(f"{control}/documents", timeout=30).json()
    assert any(d["id"] == did for d in lib)              # still in the library
