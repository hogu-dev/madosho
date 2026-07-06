# tests/integration/test_pipelines_compose_e2e.py
"""Slow: needs the compose stack up. Unlike the eval e2e, this test does NOT
need a real LLM provider - it only exercises the pipeline retrieval path and
asserts that hits carry pipeline attribution. Gated by docker presence exactly
like test_f; deselected by default via the `slow` marker
(addopts = "-m 'not slow'").

The second pipeline differs from the default by PARSER only (pypdfium2 vs
docling). Both parsers live under the same 'docling' install extra and need no
additional model downloads, so every proof in this test is live-runnable on
the stock compose stack without any extra configuration."""
import os
import shutil
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.slow
ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Alt parser for the second pipeline.
#
# The built-in registry has exactly one production chunker ("docling-hybrid")
# and one production embedder ("granite-embedding-english-r2"), so we
# distinguish the second pipeline on the PARSER axis instead:
#
#   default  ->  parser="docling"     (full ML layout + table detection)
#   alt      ->  parser="pypdfium2"   (fast CPU-only text extraction)
#
# Both are registered in backend/madosho/core/registry.py (lines 36-37) and ship
# under the same 'docling' install extra, so no additional model or service is
# required. The collection dimensions are identical (same embedder), and the
# two indexes are still fully independent.
ALT_PARSER = "pypdfium2"


@pytest.fixture(scope="module")
def stack():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    # No LLM provider check here - this test only retrieves, does not generate.
    try:
        subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=ROOT, check=True)
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

        yield {"control": "http://127.0.0.1:8000", "query": "http://127.0.0.1:8001"}
    finally:
        subprocess.run(
            ["docker", "compose", "logs", "--tail", "80", "worker", "app", "query"],
            cwd=ROOT,
            check=False,
        )
        subprocess.run(["docker", "compose", "down", "-v"], cwd=ROOT, check=False)


# ---------------------------------------------------------------------------
# Helpers - mirror test_f's style verbatim so a future merge is trivial.

def _wait_indexed(control: str, doc_id: int, timeout: int = 900) -> str:
    """Poll GET /documents/{doc_id} until status is 'indexed' or 'failed'."""
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{control}/documents/{doc_id}", timeout=30).json()["status"]
        if status in ("indexed", "failed"):
            break
        time.sleep(5)
    else:
        pytest.fail(
            f"document {doc_id} did not reach indexed within {timeout}s; "
            f"last status: {status!r}")
    return status


def _wait_pipeline_indexed(query: str, corpus_name: str, pipeline_name: str,
                           timeout: int = 900) -> dict:
    """Poll GET /corpora/{name}/pipelines on the query plane until the named
    pipeline's status is 'indexed' (or 'failed'). Returns the pipeline dict."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = httpx.get(f"{query}/corpora/{corpus_name}/pipelines", timeout=30)
        if r.status_code == 200:
            for p in r.json():
                if p["name"] == pipeline_name:
                    last = p
                    if p["status"] in ("indexed", "failed"):
                        return p
        time.sleep(5)
    pytest.fail(
        f"pipeline '{pipeline_name}' in corpus '{corpus_name}' did not reach "
        f"indexed within {timeout}s; last entry: {last!r}")


# ---------------------------------------------------------------------------
# The five proofs

def test_pipelines_on_a_document_e2e(stack, contract_pdf):
    control = stack["control"]
    query = stack["query"]

    # -----------------------------------------------------------------------
    # Proof 1: create corpus, upload document, wait for ingest -> indexed.
    # The ingest worker auto-builds the default <doc>_docling pipeline.

    r = httpx.post(f"{control}/corpora", json={"name": "e2e-g"}, timeout=30)
    assert r.status_code == 201, f"corpus create failed: {r.status_code} {r.text}"
    cid = r.json()["id"]
    corpus_config = r.json()["config"]

    with open(contract_pdf, "rb") as fh:
        r = httpx.post(
            f"{control}/corpora/{cid}/documents",
            files={"file": ("contract.pdf", fh, "application/pdf")},
            timeout=60,
        )
    assert r.status_code == 202, f"document upload failed: {r.status_code} {r.text}"
    did = r.json()["id"]

    status = _wait_indexed(control, did)
    assert status == "indexed", f"document ended in status {status!r}"

    # -----------------------------------------------------------------------
    # Proof 2: GET /corpora/{name}/pipelines (query plane) shows a _docling
    # pipeline that is marked effective.

    r = httpx.get(f"{query}/corpora/e2e-g/pipelines", timeout=30)
    assert r.status_code == 200, f"list pipelines failed: {r.status_code} {r.text}"
    pipeline_list = r.json()
    assert len(pipeline_list) >= 1, "expected at least one pipeline after ingest"

    docling_pipelines = [p for p in pipeline_list if p["name"].endswith("_docling")]
    assert docling_pipelines, (
        f"expected a _docling pipeline; got: {[p['name'] for p in pipeline_list]}")

    default_pipeline = docling_pipelines[0]
    assert default_pipeline["status"] == "indexed", (
        f"default pipeline status is {default_pipeline['status']!r}, expected 'indexed'")
    assert default_pipeline["effective"] is True, (
        "expected the default _docling pipeline to be marked effective")

    # -----------------------------------------------------------------------
    # Proof 3: POST /documents/{id}/pipelines builds a SECOND pipeline into
    # its own index, using a different parser (pypdfium2 instead of docling).
    # Poll until indexed.
    #
    # Derive the alt config from the corpus's real config so the only diff is
    # the parser - a minimal and realistic delta. The collection dimensions are
    # identical (same embedder), so no extra model is required.

    import copy
    alt_config = copy.deepcopy(corpus_config)
    alt_config["ingest"]["parser"] = ALT_PARSER
    # Remove the collection key if present - the server stamps it per-pipeline.
    alt_config.get("ingest", {}).get("store", {}).get("qdrant", {}).pop(
        "collection", None)

    alt_pipeline_name = "contract_pypdfium2"
    r = httpx.post(
        f"{control}/documents/{did}/pipelines",
        json={"name": alt_pipeline_name, "config": alt_config},
        timeout=60,
    )
    assert r.status_code == 202, (
        f"create second pipeline failed: {r.status_code} {r.text}")

    alt_pipeline = _wait_pipeline_indexed(query, "e2e-g", alt_pipeline_name)
    assert alt_pipeline["status"] == "indexed", (
        f"second pipeline ended in status {alt_pipeline['status']!r}")

    # -----------------------------------------------------------------------
    # Proof 4: POST /query with no `pipelines` key returns hits, each with a
    # `pipeline` attribution. The corpus query routes each doc through its
    # effective pipeline; assert every hit carries a known pipeline attribution.

    r = httpx.post(
        f"{query}/query",
        json={"corpus": "e2e-g", "prompt": "What is the termination notice period?"},
        timeout=60,
    )
    assert r.status_code == 200, f"query failed: {r.status_code} {r.text}"
    body = r.json()
    hits = body.get("hits", [])
    assert hits, "expected at least one hit from /query"
    for h in hits:
        assert "pipeline" in h, f"hit missing 'pipeline' attribution: {h}"

    # corpus query (no override) routes each doc through its effective pipeline;
    # assert every hit carries a known pipeline attribution.
    known_names = {p["name"] for p in pipeline_list} | {alt_pipeline_name}
    for h in hits:
        assert h["pipeline"] in known_names, (
            f"hit pipeline {h['pipeline']!r} is not a known pipeline: {known_names}")

    # -----------------------------------------------------------------------
    # Proof 5: POST /query with pipelines=["<alt pipeline name>"] returns hits
    # all attributed to that second pipeline (override routing works).

    r = httpx.post(
        f"{query}/query",
        json={
            "corpus": "e2e-g",
            "prompt": "What is the termination notice period?",
            "pipelines": [alt_pipeline_name],
        },
        timeout=60,
    )
    assert r.status_code == 200, (
        f"named-pipeline query failed: {r.status_code} {r.text}")
    body2 = r.json()
    hits2 = body2.get("hits", [])
    assert hits2, "expected at least one hit from named-pipeline /query"
    for h in hits2:
        assert h["pipeline"] == alt_pipeline_name, (
            f"expected all hits attributed to '{alt_pipeline_name}', "
            f"got {h['pipeline']!r}")
