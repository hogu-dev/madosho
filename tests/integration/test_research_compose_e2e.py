# tests/integration/test_research_compose_e2e.py
"""Opt-in live e2e: drive a full research run THROUGH the control plane
(POST /corpora/{id}/research -> worker runs research_agent -> GET the report). Like
test_research_agent_compose_e2e.py it does NOT bring anything up. Run with:

    docker compose up -d            # stack seeded (e.g. the aerospace corpus)
    # ensure the worker has MADOSHO_LLM_API_BASE/_KEY set (compose.override does)
    export RESEARCH_AGENT_PROVIDER=... RESEARCH_AGENT_MODEL=...
    .venv/bin/python -m pytest tests/integration/test_research_compose_e2e.py -m slow -v
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.slow

CONTROL = os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000")
CORPUS = os.environ.get("RESEARCH_AGENT_E2E_CORPUS", "aerospace")
# Auth is ON by default, so these raw calls authenticate as the seeded bootstrap
# admin account (admin/admin unless overridden). Login yields a session cookie the
# control plane accepts on both planes -- no API key needs minting.
USER = os.environ.get("MADOSHO_TEST_USER", "admin")
PASSWORD = os.environ.get("MADOSHO_TEST_PASSWORD", "admin")

_cookie: str | None = None


def _login() -> str | None:
    body = json.dumps({"username": USER, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{CONTROL}/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.headers.get("Set-Cookie", "")
            return raw.split(";", 1)[0] if raw else None
    except Exception:
        return None  # auth disabled / no login endpoint -> unauthenticated calls


def _headers(extra: dict | None = None) -> dict:
    h = dict(extra or {})
    if _cookie:
        h["Cookie"] = _cookie
    return h


def _get(path):
    req = urllib.request.Request(f"{CONTROL}{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _post(path, body):
    req = urllib.request.Request(
        f"{CONTROL}{path}", data=json.dumps(body).encode(),
        headers=_headers({"Content-Type": "application/json"}), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _stack_up() -> bool:
    # A response of ANY status (including 401) means the stack is reachable; only a
    # connection failure means it is not running. The old probe wrongly treated a
    # 401 (auth on) as "stack down" and skipped the whole suite.
    try:
        urllib.request.urlopen(f"{CONTROL}/health", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_stack_and_provider():
    global _cookie
    if not _stack_up():
        pytest.skip("compose stack not reachable - start it (docker compose up -d)")
    _cookie = _login()
    if not os.environ.get("RESEARCH_AGENT_PROVIDER") or not os.environ.get("RESEARCH_AGENT_MODEL"):
        pytest.skip("set RESEARCH_AGENT_PROVIDER and RESEARCH_AGENT_MODEL to run this")


def _corpus_id(name: str) -> int:
    for c in _get("/corpora"):
        if c["name"] == name:
            return c["id"]
    pytest.skip(f"corpus {name!r} not seeded; ingest a corpus first")


def test_research_run_through_control_plane_produces_report():
    cid = _corpus_id(CORPUS)
    launched = _post(f"/corpora/{cid}/research", {
        "prompt": f"Summarize what the {CORPUS} documents say about flight control.",
        "source": "rag",
        "llm": {"provider": os.environ["RESEARCH_AGENT_PROVIDER"],
                "model": os.environ["RESEARCH_AGENT_MODEL"]},
    })
    rid = launched["id"]
    assert launched["status"] == "pending"

    deadline = time.monotonic() + 600
    run = None
    while time.monotonic() < deadline:
        run = _get(f"/corpora/{cid}/research/{rid}")
        if run["status"] in ("done", "failed"):
            break
        time.sleep(3)

    assert run is not None and run["status"] == "done", run
    assert run["report_markdown"] and len(run["report_markdown"]) > 50
    assert run["stop_reason"] in ("final", "round_cap", "no_tools_used")
