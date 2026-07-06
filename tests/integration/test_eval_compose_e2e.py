# tests/integration/test_eval_compose_e2e.py
"""Slow: needs the compose stack up AND a real LLM provider for golden-set
generation (MADOSHO_LLM_API_BASE / MADOSHO_LLM_API_KEY). Mirrors the ratings e2e;
the fast suite skips it via the `slow` marker (addopts = "-m 'not slow'")."""
import os
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
    if not os.environ.get("MADOSHO_LLM_API_BASE"):
        pytest.skip("no LLM provider configured for golden-set generation")
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


def test_eval_run_fills_cube_and_maybe_proposes(stack, contract_pdf):
    control = stack["control"]

    r = httpx.post(f"{control}/corpora", json={"name": "e2e-eval"}, timeout=30)
    assert r.status_code == 201, f"corpus create failed: {r.status_code} {r.text}"
    cid = r.json()["id"]

    with open(contract_pdf, "rb") as fh:
        r = httpx.post(
            f"{control}/corpora/{cid}/documents",
            files={"file": ("doc.pdf", fh, "application/pdf")},
            timeout=60,
        )
    assert r.status_code == 202, f"document upload failed: {r.status_code} {r.text}"
    did = r.json()["id"]

    deadline = time.monotonic() + 900
    status = None
    while time.monotonic() < deadline:
        status = httpx.get(f"{control}/documents/{did}", timeout=30).json()["status"]
        if status in ("indexed", "failed"):
            break
        time.sleep(5)
    else:
        pytest.fail(f"document did not reach indexed within timeout; last status: {status!r}")
    assert status == "indexed", f"document ended in status {status!r}"

    # Provider is derived from MADOSHO_LLM_API_BASE being set (required by stack fixture).
    # The model is optional; fall back to a sensible default for local vision-lane setups.
    model = os.environ.get("MADOSHO_EVAL_MODEL", "gemma-e4b")
    run_r = httpx.post(
        f"{control}/corpora/{cid}/evals",
        json={
            "sampling": {
                "n_docs": 1,
                "questions_per_doc": 3,
                "llm": {"provider": "openai", "model": model},
            },
            "token_budget": 50000,
        },
        timeout=30,
    )
    assert run_r.status_code == 201, f"eval launch failed: {run_r.status_code} {run_r.text}"
    rid = run_r.json()["id"]

    deadline = time.monotonic() + 1200
    eval_status = None
    while time.monotonic() < deadline:
        eval_status = httpx.get(f"{control}/evals/{rid}", timeout=30).json()["status"]
        if eval_status in ("done", "failed", "cancelled"):
            break
        time.sleep(5)
    assert eval_status == "done", f"eval run ended in {eval_status!r}"

    cube = httpx.get(f"{control}/corpora/{cid}/ratings", timeout=30).json()
    # Corpus-level f-empirical cells are written into the rollup row; document
    # rows carry per-document sources.  Gather both to check for the label.
    sources = {
        c["source"]
        for row in [cube["rollup"], *cube["documents"]]
        for c in row["cells"].values()
    }
    assert "f-empirical" in sources, "expected f-empirical cube cells after an eval run"
