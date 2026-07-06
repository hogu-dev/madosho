"""The toolserver forwards each caller's bearer token to every upstream call.

How it works (teaching note):
  FastAPI's async yield-dependency sets the http contextvar in the request's own
  asyncio task. When FastAPI then calls the SYNC handler via anyio.to_thread.run_sync,
  anyio copies THAT task's context (including the contextvar) into the worker thread.
  Each concurrent request is its own asyncio task with its own context copy, so there
  is no bleed between callers. Starlette BaseHTTPMiddleware does NOT give this
  guarantee because the downstream app runs in a separate task; the async dependency
  approach is deliberate.

Also covered here: the toolserver relays upstream 4xx status codes faithfully.

  The bug this covers: before the fix, _guard() always raised HTTPException(502)
  on any CliError, even when the upstream responded 401 or 403. A read key denied
  a write would get 502 ("bad gateway") instead of 403 ("scope denied"). The tests
  below were written RED first (failing against the 502-collapse) then GREEN after
  the fix.
"""
from __future__ import annotations

import io
import json
import threading
import unittest.mock
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from madosho_cli import http
from madosho_toolserver.app import app


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _Resp:
    """Minimal fake for urllib.request.urlopen return value."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_SEARCH_REPLY = {"hits": [{"text": "t", "score": 1.0, "citation": "a.pdf p.1"}]}


def _make_fake_urlopen(captured: list) -> object:
    """Return a fake urlopen that appends the Authorization header to `captured`."""
    def fake(req, *a, **kw):
        # urllib.request.Request capitalizes the first letter of each header name;
        # get_header() does the same lookup so this always finds "Authorization".
        auth = req.get_header("Authorization") or ""
        captured.append(auth)
        return _Resp(_SEARCH_REPLY)
    return fake


# ---------------------------------------------------------------------------
# Test 1: bearer on toolserver request reaches upstream
# ---------------------------------------------------------------------------

def test_bearer_forwarded_upstream(monkeypatch):
    """Authorization: Bearer abc on the toolserver request -> upstream carries it."""
    captured: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _make_fake_urlopen(captured))

    r = TestClient(app).post(
        "/search",
        json={"corpus": "c", "query": "q"},
        headers={"Authorization": "Bearer abc"},
    )

    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0] == "Bearer abc"


# ---------------------------------------------------------------------------
# Test 2 (CRITICAL): no bearer-bleed between concurrent requests
# ---------------------------------------------------------------------------

def test_no_bleed_concurrent_bearers():
    """Two concurrent requests with DIFFERENT bearers each forward their OWN bearer.

    Concurrency mechanism: two OS threads each drive their own TestClient call.
    A threading.Barrier ensures both are in-flight simultaneously so the test
    genuinely exercises concurrent contextvar copies in the threadpool, not just
    sequential isolation.

    No-bleed proof: if the contextvar leaked (e.g. one request stomped the other),
    both upstream calls would carry the same bearer. The assertion that BOTH distinct
    bearers appear in `captured` is a tight proof: exactly 2 upstream calls, each
    with a distinct bearer.
    """
    captured: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    statuses: dict[str, int] = {}

    def fake_urlopen(req, *a, **kw):
        auth = req.get_header("Authorization") or ""
        with lock:
            captured.append(auth)
        return _Resp(_SEARCH_REPLY)

    def run_request(bearer: str) -> None:
        # Both threads reach barrier.wait() before either proceeds, guaranteeing
        # they are in-flight at the same time (true concurrency, not sequencing).
        barrier.wait()
        with unittest.mock.patch("urllib.request.urlopen", fake_urlopen):
            r = TestClient(app).post(
                "/search",
                json={"corpus": "c", "query": "q"},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        with lock:
            statuses[bearer] = r.status_code

    t1 = threading.Thread(target=run_request, args=("tok-aaa",))
    t2 = threading.Thread(target=run_request, args=("tok-bbb",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert statuses.get("tok-aaa") == 200, f"tok-aaa status: {statuses}"
    assert statuses.get("tok-bbb") == 200, f"tok-bbb status: {statuses}"
    # If bleed had occurred, captured would contain one bearer twice; both must appear.
    assert set(captured) == {"Bearer tok-aaa", "Bearer tok-bbb"}, (
        f"bearer bleed detected -- captured: {captured}"
    )


# ---------------------------------------------------------------------------
# Test 3: no Authorization header -> fall back to env MADOSHO_API_KEY
# ---------------------------------------------------------------------------

def test_no_auth_header_falls_back_to_env(monkeypatch):
    """No Authorization header on toolserver request -> upstream gets env key."""
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_envkey")
    captured: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _make_fake_urlopen(captured))

    r = TestClient(app).post("/search", json={"corpus": "c", "query": "q"})

    assert r.status_code == 200
    assert captured[0] == "Bearer mdsh_envkey"


def test_no_auth_no_env_no_upstream_header(monkeypatch):
    """No Authorization header AND no env key -> upstream gets no auth header."""
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    captured: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _make_fake_urlopen(captured))

    r = TestClient(app).post("/search", json={"corpus": "c", "query": "q"})

    assert r.status_code == 200
    # No auth header -> captured value is "" (the fallback in _make_fake_urlopen)
    assert captured[0] == ""


# ---------------------------------------------------------------------------
# Test 4: /health stays open (no dependency, no auth required)
# ---------------------------------------------------------------------------

def test_health_open_no_auth():
    """/health must remain open; the inject-bearer dependency must NOT be on it."""
    # If the dependency were on /health, it would still pass (the dependency
    # permits any request), but this ensures /health is not accidentally gated.
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests 5-8: toolserver relays upstream 4xx faithfully; 502 only for
# genuine bad-gateway conditions (connection failure / upstream 5xx).
#
# These were written RED first: before the fix, _guard() always emitted 502 for
# any CliError regardless of the upstream code.  The fix makes _guard() read
# CliError.status and relay 4xx codes unchanged; these tests turned GREEN after.
# ---------------------------------------------------------------------------

def _make_upstream_http_error(code: int, message: str) -> urllib.error.HTTPError:
    """Build a urllib HTTPError that simulates an upstream responding with `code`."""
    body = json.dumps({"detail": message}).encode()
    return urllib.error.HTTPError(
        url="http://fake-control/corpora",
        code=code,
        msg=message,
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


def test_upstream_403_relayed_as_403(monkeypatch):
    """Upstream 403 (scope denied) -> toolserver responds 403, not 502.

    Read key -> POST /create-corpus -> control plane 403 -> _guard relays 403.
    Before the fix this was 502 ("bad gateway"), masking the real scope error.
    """
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, *a, **kw: (_ for _ in ()).throw(
            _make_upstream_http_error(403, "insufficient scope")
        ),
    )
    r = TestClient(app).post(
        "/create-corpus",
        json={"name": "test-corpus"},
        headers={"Authorization": "Bearer mdsh_readkey"},
    )
    assert r.status_code == 403, f"expected 403 (scope denied), got {r.status_code}"
    assert "403" in r.json()["detail"]


def test_upstream_401_relayed_as_401(monkeypatch):
    """Upstream 401 (invalid/missing key) -> toolserver responds 401, not 502."""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, *a, **kw: (_ for _ in ()).throw(
            _make_upstream_http_error(401, "unauthorized")
        ),
    )
    r = TestClient(app).post(
        "/list-corpora",
        json={},
        headers={"Authorization": "Bearer mdsh_badkey"},
    )
    assert r.status_code == 401, f"expected 401 (unauthorized), got {r.status_code}"
    assert "401" in r.json()["detail"]


def test_connection_failure_still_502(monkeypatch):
    """URLError (connection refused / host unreachable) -> toolserver still 502.

    This is a genuine bad-gateway condition: the upstream is down, not the
    caller's fault.  502 is the correct proxy response here.
    Regression guard: this must stay 502 even after the 4xx-relay fix.
    """
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, *a, **kw: (_ for _ in ()).throw(
            urllib.error.URLError("Connection refused")
        ),
    )
    r = TestClient(app).post(
        "/list-corpora",
        json={},
        headers={"Authorization": "Bearer mdsh_key"},
    )
    assert r.status_code == 502, f"connection failure should stay 502, got {r.status_code}"


def test_upstream_500_relayed_as_502(monkeypatch):
    """Upstream 5xx -> toolserver responds 502 (upstream server error, not client error)."""
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, *a, **kw: (_ for _ in ()).throw(
            _make_upstream_http_error(500, "internal server error")
        ),
    )
    r = TestClient(app).post(
        "/list-corpora",
        json={},
        headers={"Authorization": "Bearer mdsh_key"},
    )
    assert r.status_code == 502, f"upstream 5xx should become 502, got {r.status_code}"
