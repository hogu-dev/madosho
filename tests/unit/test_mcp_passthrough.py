"""The MCP-over-HTTP server forwards each caller's bearer token upstream.

stdio transport is unchanged: it reads MADOSHO_API_KEY from the environment
of the process that spawns it. HTTP transport: the incoming Authorization
header is extracted from the ASGI scope, set in the http contextvar for the
duration of the dispatch, and reset in a finally block.

How the bearer-forwarding works end-to-end (the tested path):
  ASGI scope Authorization header
    -> server._extract_bearer(scope)  [production parsing function]
    -> http.set_request_token(token)  [contextvar, task-local]
    -> await session_manager.handle_request(...)
         -> _call_tool -> dispatch -> core -> http.get_json/post_json
              -> urlopen with Authorization: Bearer <token>
    -> http.reset_request_token(tok)  [finally; no-bleed guarantee]
"""
from __future__ import annotations

import asyncio
import json
import urllib.request

from madosho_cli import http
from madosho_mcp import server


# ---------------------------------------------------------------------------
# Shared helper: minimal fake urlopen
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


# The /corpora endpoint returns a raw list; core.list_corpora() wraps it.
_CORPORA_REPLY = [{"id": 1, "name": "test"}]


def _fake_urlopen(captured: list):
    """Return a fake urlopen that records the Authorization header."""
    def fake(req, *a, **kw):
        # urllib capitalises header names; get_header does the same lookup.
        auth = req.get_header("Authorization") or ""
        captured.append(auth)
        return _Resp(_CORPORA_REPLY)
    return fake


# ---------------------------------------------------------------------------
# Unit tests for _extract_bearer (the named production parsing function)
# ---------------------------------------------------------------------------

def test_extract_bearer_standard():
    """Standard "Bearer <token>" header is parsed correctly."""
    scope = {"headers": [(b"authorization", b"Bearer secrettoken")]}
    assert server._extract_bearer(scope) == "secrettoken"


def test_extract_bearer_scheme_case_insensitive():
    """Lowercase "bearer" scheme prefix is also accepted."""
    scope = {"headers": [(b"authorization", b"bearer lowercasetoken")]}
    assert server._extract_bearer(scope) == "lowercasetoken"


def test_extract_bearer_no_header_returns_none():
    """No Authorization header -> None."""
    assert server._extract_bearer({"headers": []}) is None


def test_extract_bearer_non_bearer_scheme_returns_none():
    """Basic auth scheme is not a bearer token; return None."""
    scope = {"headers": [(b"authorization", b"Basic abc123")]}
    assert server._extract_bearer(scope) is None


def test_extract_bearer_missing_headers_key():
    """scope with no 'headers' key at all -> None (defensive)."""
    assert server._extract_bearer({}) is None


# ---------------------------------------------------------------------------
# Test 1: HTTP handle path -- real scope -> contextvar set -> upstream carries it
# ---------------------------------------------------------------------------

def test_bearer_forwarded_via_http_handle(monkeypatch):
    """Authorization: Bearer xyz in ASGI scope -> mocked upstream urlopen carries it.

    How this exercises production code (not a copy):
    - Extracts the real `handle` closure from the built Starlette app's /mcp mount.
    - Passes an ASGI scope with an Authorization header to the real handle().
    - handle() calls the real _extract_bearer(scope) [production parsing].
    - handle() calls http.set_request_token(token) [contextvar, same task].
    - Patched session_manager.handle_request then calls server.dispatch("list-corpora",
      {}) to exercise core -> http.get_json -> urlopen.
    - urlopen is patched to capture the Authorization header it receives.
    - The final assertion is on the upstream urlopen call, proving the full chain.
    """
    import mcp.server.streamable_http_manager as smm

    captured_auth: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(captured_auth))

    async def fake_handle_request(self, scope, receive, send):
        # The contextvar is live here (inside handle's try block).
        # Calling dispatch exercises the real core -> http -> urlopen path.
        server.dispatch("list-corpora", {})

    monkeypatch.setattr(
        smm.StreamableHTTPSessionManager, "handle_request", fake_handle_request
    )

    s = server.build_server()
    app_obj = server.build_http_app(s)

    # Get the real handle closure directly from the Starlette Mount.
    # This avoids Starlette routing overhead while still calling the exact same
    # production closure that runs in production.
    handle_fn = next(
        r for r in app_obj.routes if getattr(r, "path", "") == "/mcp"
    ).app

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"authorization", b"Bearer xyz")],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(msg):
        pass

    asyncio.run(handle_fn(scope, receive, send))

    assert len(captured_auth) == 1, f"expected 1 upstream call, got: {captured_auth}"
    assert captured_auth[0] == "Bearer xyz", (
        f"upstream call did not carry 'Bearer xyz'; got: {captured_auth[0]!r}"
    )


# ---------------------------------------------------------------------------
# Test 1b: contextvar is reset after handle() returns (no-bleed guarantee)
# ---------------------------------------------------------------------------

def test_contextvar_reset_after_handle(monkeypatch):
    """The production `finally` in handle() restores the contextvar after the request.

    If reset fails, a subsequent request on the same task could inherit a stale
    token. This test BITES: removing the `finally: http.reset_request_token(tok)`
    in handle() makes it fail.

    Why everything runs inside ONE asyncio.run(scenario()): asyncio.run creates a
    fresh task whose context is a COPY of the caller's. Any ContextVar.set() inside
    the task mutates that copy, not the caller's context. So the before/after read
    AND the awaited handle() must all live in the SAME task, or the post-call read
    would observe the untouched caller context and pass vacuously. By awaiting the
    real handle_fn inside scenario() and reading the contextvar before and after in
    that same task, we observe handle()'s own set+reset; if the production reset is
    gone, `after` stays at "request_token" and the assertion fails.
    """
    import mcp.server.streamable_http_manager as smm

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen([]))

    async def fake_handle_request(self, scope, receive, send):
        server.dispatch("list-corpora", {})

    monkeypatch.setattr(
        smm.StreamableHTTPSessionManager, "handle_request", fake_handle_request
    )

    s = server.build_server()
    app_obj = server.build_http_app(s)
    handle_fn = next(
        r for r in app_obj.routes if getattr(r, "path", "") == "/mcp"
    ).app

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"authorization", b"Bearer request_token")],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(msg):
        pass

    async def scenario():
        # Read the contextvar in THIS task before driving handle().
        before = http._request_token.get()
        await handle_fn(scope, receive, send)
        # handle() set the contextvar to "request_token" then (production finally)
        # reset it. After the call it must be back to `before`, NOT "request_token".
        after = http._request_token.get()
        assert after == before, (
            "handle() did not restore the contextvar after the request; "
            f"before={before!r} after={after!r}"
        )
        assert after != "request_token", (
            "the request's bearer leaked past handle() -- the finally-reset "
            f"did not run; after={after!r}"
        )

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Test 2: stdio regression -- env key still forwarded when contextvar is unset
# ---------------------------------------------------------------------------

def test_stdio_dispatch_uses_env_key(monkeypatch):
    """Stdio: dispatch with MADOSHO_API_KEY in env and contextvar unset -> env key forwarded.

    This is the unchanged CLI/stdio code path. The MCP server in stdio mode
    does NOT call _extract_bearer or set_request_token; _auth_headers() falls
    back to MADOSHO_API_KEY. Verifies that adding T3's HTTP logic did not break
    the env-fallback path.
    """
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_envkey")

    captured: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(captured))

    # Explicitly unset the contextvar (simulates stdio path: no bearer extraction).
    tok = http.set_request_token(None)
    try:
        server.dispatch("list-corpora", {})
    finally:
        http.reset_request_token(tok)

    assert len(captured) == 1
    assert captured[0] == "Bearer mdsh_envkey", (
        f"stdio dispatch did not use env key; got: {captured[0]!r}"
    )
