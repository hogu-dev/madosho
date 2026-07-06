# tests/integration/test_ratings_compose_e2e.py
"""Slow: needs the compose stack up. Mirrors the citations e2e. Marked so the fast suite skips it."""
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


def test_static_cube_populates_after_ingest(stack, contract_pdf):
    control = stack["control"]

    r = httpx.post(f"{control}/corpora", json={"name": "e2e-ratings"}, timeout=30)
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

    cube = httpx.get(f"{control}/corpora/{cid}/ratings", timeout=30).json()
    assert cube["documents"], "expected a static cube row after ingest"
    assert set(cube["documents"][0]["cells"]) >= {"extraction", "embed", "chunk"}
