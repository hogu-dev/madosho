"""Per-request bearer passthrough via contextvars.

The contextvar lets the toolserver and MCP-over-HTTP proxies override the
outgoing auth header for each caller's request, without touching env vars or
threading a token through ~15 core.py function signatures.
"""
from __future__ import annotations

from madosho_cli import http


def test_contextvar_beats_env(monkeypatch):
    """contextvar value wins over MADOSHO_API_KEY when both are set."""
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_envkey")
    tok = http.set_request_token("mdsh_ctxkey")
    try:
        assert http._auth_headers() == {"Authorization": "Bearer mdsh_ctxkey"}
    finally:
        http.reset_request_token(tok)


def test_env_used_when_contextvar_unset(monkeypatch):
    """No contextvar -> falls back to MADOSHO_API_KEY (CLI unchanged)."""
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_envonly")
    # ensure contextvar is cleared (default)
    tok = http.set_request_token(None)
    try:
        assert http._auth_headers() == {"Authorization": "Bearer mdsh_envonly"}
    finally:
        http.reset_request_token(tok)


def test_neither_set_no_auth_header(monkeypatch):
    """Neither contextvar nor env -> no Authorization header."""
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    tok = http.set_request_token(None)
    try:
        assert http._auth_headers() == {}
    finally:
        http.reset_request_token(tok)


def test_reset_restores_prior_state(monkeypatch):
    """reset_request_token restores the previous value; no leakage after scope."""
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)

    # set an outer token
    outer_tok = http.set_request_token("mdsh_outer")
    assert http._auth_headers() == {"Authorization": "Bearer mdsh_outer"}

    # enter an inner scope with a different token
    inner_tok = http.set_request_token("mdsh_inner")
    assert http._auth_headers() == {"Authorization": "Bearer mdsh_inner"}

    # reset inner -> should be back to outer
    http.reset_request_token(inner_tok)
    assert http._auth_headers() == {"Authorization": "Bearer mdsh_outer"}

    # reset outer -> should be back to module default (None)
    http.reset_request_token(outer_tok)
    assert http._auth_headers() == {}
