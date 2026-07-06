"""the madosho-mcp entrypoint routes to stdio (default) or --http, and builds a
real Starlette app for the HTTP transport. We never actually serve (no blocking)."""
from __future__ import annotations

import pytest

from madosho_mcp import server


def test_run_defaults_to_stdio(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "serve_stdio", lambda s: called.setdefault("stdio", True))
    monkeypatch.setattr(server, "serve_http",
                        lambda s, host, port: called.setdefault("http", (host, port)))
    rc = server.run([])
    assert rc == 0
    assert called == {"stdio": True}


def test_run_http_routes_with_host_port(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "serve_stdio", lambda s: called.setdefault("stdio", True))
    monkeypatch.setattr(server, "serve_http",
                        lambda s, host, port: called.setdefault("http", (host, port)))
    rc = server.run(["--http", "--host", "0.0.0.0", "--port", "9000"])
    assert rc == 0
    assert called == {"http": ("0.0.0.0", 9000)}


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        server.run(["--help"])
    assert exc.value.code == 0


def test_build_http_app_is_starlette_with_mcp_mount():
    from starlette.applications import Starlette
    app = server.build_http_app(server.build_server())
    assert isinstance(app, Starlette)
    # the streamable-HTTP transport is mounted at /mcp
    assert any(getattr(r, "path", "") == "/mcp" for r in app.routes)
