"""HTTP transport for the madosho CLI.

Stdlib only (urllib) - matches examples/cli, adds no dependency, stays
permissive-OSS-only. Endpoints come from env vars so the same
CLI drives a local stack, compose, or a remote deployment.
"""
from __future__ import annotations

import contextvars
import json
import os
import secrets
import urllib.error
import urllib.request
from typing import Any

# Per-request bearer token override.
#
# WHY a contextvar and not a function argument:
#   Threading a token through _auth_headers -> get_json/post_json/post_multipart
#   -> core.py would touch ~15 function signatures with no benefit to callers
#   that do not need per-request override (i.e. the CLI itself, which reads the
#   env key once and never changes it mid-run).
#
# WHY not mutate os.environ:
#   The toolserver (:8088) and MCP-over-HTTP proxy are async/concurrent - many
#   requests may be in-flight at once. Mutating a process-global env var would
#   race: request A's token could be read by request B's _auth_headers() call.
#   contextvars are per-asyncio-task (and per-thread), so each request gets
#   its own isolated value with zero coordination overhead.
#
# Usage (in a FastAPI yield-dependency or try/finally teardown):
#
#   tok = http.set_request_token(caller_bearer)
#   try:
#       ... forward request upstream ...
#   finally:
#       http.reset_request_token(tok)
_request_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_request_token", default=None
)


def set_request_token(token: str | None) -> contextvars.Token:
    """Set the per-request bearer for this async task / thread.

    Returns the Token produced by ContextVar.set(); pass it to
    reset_request_token() to restore the prior value when the request ends.
    """
    return _request_token.set(token)


def reset_request_token(tok: contextvars.Token) -> None:
    """Restore the contextvar to the state captured in tok.

    Call this in a finally block or FastAPI yield-dependency teardown so the
    token does not leak into the next request handled by the same task.
    """
    _request_token.reset(tok)


class CliError(Exception):
    """A user-facing failure (bad HTTP status, unreachable host, bad JSON).

    main() catches this, prints the message to stderr, and exits non-zero - the
    exact signal a tool provider keys off to surface a structured tool
    error to the agent.

    The optional `status` attribute carries the upstream HTTP status code when the
    error originated from a remote HTTP response (401, 403, 404, 422, 5xx, ...).
    It is None when the error has no upstream HTTP code (connection refused,
    bad JSON, a logic-level CliError raised by core.py). Callers that proxy
    upstream requests (e.g. the toolserver) read `.status` to decide which HTTP
    code to relay to their own callers; callers that just print the message (the
    CLI) ignore it.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        # WHY structured status and not string-parsing the message:
        #   A proxy (toolserver) needs to relay the upstream 4xx to the caller so
        #   the caller's error ("your key is read-only", "not found", etc.) is not
        #   hidden behind a misleading 502.  String-parsing "HTTP 403 from ..." is
        #   fragile -- the format can change, and it conflates the status with the
        #   message text.  A typed int attribute is stable, cheap, and explicit.
        self.status: int | None = status


def query_base() -> str:
    return os.environ.get("MADOSHO_QUERY_URL", "http://localhost:8001").rstrip("/")


def control_base() -> str:
    return os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000").rstrip("/")


def _auth_headers() -> dict:
    # Prefer the per-request contextvar (set by the toolserver/MCP proxy for
    # the calling client's own bearer); else fall back to the process-wide env
    # key (normal CLI / single-client usage).
    key = _request_token.get() or os.environ.get("MADOSHO_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _read(req: urllib.request.Request) -> Any:
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted, env-configured URL)
            return json.load(resp)
    except urllib.error.HTTPError as e:  # subclass of URLError - must come first
        body = e.read().decode(errors="replace")
        raise CliError(f"HTTP {e.code} from {req.full_url}: {body}", status=e.code) from e
    except urllib.error.URLError as e:
        raise CliError(
            f"could not reach {req.full_url}: {e.reason}\n"
            "is the stack up? (docker compose ps)"
        ) from e
    except json.JSONDecodeError as e:
        raise CliError(f"bad JSON from {req.full_url}: {e}") from e


def get_json(url: str) -> Any:
    headers = {"Accept": "application/json"}
    headers.update(_auth_headers())
    return _read(urllib.request.Request(url, headers=headers))


def post_json(url: str, payload: dict) -> Any:
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers())
    return _read(
        urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
    )


def put_json(url: str, payload: dict) -> Any:
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers())
    return _read(
        urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="PUT",
        )
    )


def post_multipart(url, fields, file_path, *, field_name="file"):
    boundary = "----madosho" + secrets.token_hex(16)
    nl = b"\r\n"
    parts = []
    for name, value in fields.items():
        if value is None:
            continue
        parts.append(b"--" + boundary.encode() + nl)
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode() + nl + nl)
        parts.append(str(value).encode() + nl)
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as fh:
        file_bytes = fh.read()
    parts.append(b"--" + boundary.encode() + nl)
    parts.append((f'Content-Disposition: form-data; name="{field_name}"; '
                  f'filename="{filename}"').encode() + nl)
    parts.append(b"Content-Type: application/octet-stream" + nl + nl)
    parts.append(file_bytes + nl)
    parts.append(b"--" + boundary.encode() + b"--" + nl)
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    headers.update(_auth_headers())
    return _read(urllib.request.Request(url, data=body, headers=headers, method="POST"))
