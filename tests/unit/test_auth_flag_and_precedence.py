"""
auth_enabled default ON + bearer-wins-over-cookie precedence.

These tests pin behavior that must not regress.
"""
import pytest
from starlette.requests import Request

from madosho_server import auth, db
from madosho_server.settings import Settings

_SECRET = "w4-test-secret-not-real"


# ---------------------------------------------------------------------------
# 1. from_env: auth_enabled defaults ON
# ---------------------------------------------------------------------------

def test_from_env_unset_defaults_on(monkeypatch):
    """Unset MADOSHO_AUTH_ENABLED -> auth_enabled is True (ships ON)."""
    monkeypatch.delenv("MADOSHO_AUTH_ENABLED", raising=False)
    assert Settings.from_env().auth_enabled is True


def test_from_env_zero_is_off(monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "0")
    assert Settings.from_env().auth_enabled is False


def test_from_env_false_string_is_off(monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "false")
    assert Settings.from_env().auth_enabled is False


def test_from_env_no_string_is_off(monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "no")
    assert Settings.from_env().auth_enabled is False


def test_from_env_one_is_on(monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    assert Settings.from_env().auth_enabled is True


def test_from_env_true_string_is_on(monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "true")
    assert Settings.from_env().auth_enabled is True


def test_from_env_yes_string_is_on(monkeypatch):
    """'yes' is truthy and not in the off-set, so auth is on."""
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "yes")
    assert Settings.from_env().auth_enabled is True


def test_from_env_case_insensitive_off(monkeypatch):
    for val in ("FALSE", "False", "NO", "No"):
        monkeypatch.setenv("MADOSHO_AUTH_ENABLED", val)
        assert Settings.from_env().auth_enabled is False, f"expected False for {val!r}"


# ---------------------------------------------------------------------------
# 2. bearer-wins-over-cookie: resolve_principal prefers the Authorization
#    header when both a bearer token and a valid session cookie are present.
#    These tests pin that precedence.
# ---------------------------------------------------------------------------

def _fresh_db(tmp_path, name="w4.db"):
    db.configure_engine(f"sqlite:///{tmp_path / name}")
    db.create_all()


def _settings(tmp_path, db_name="w4.db"):
    return Settings(
        database_url=f"sqlite:///{tmp_path / db_name}",
        qdrant_url="http://localhost:6333",
        filestore_dir=str(tmp_path / "fs"),
        corpora_dir=str(tmp_path / "co"),
        session_secret=_SECRET,
    )


def _build_request(bearer_raw: str, cookie_token: str) -> Request:
    """Starlette Request carrying BOTH an Authorization header AND a session cookie."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/corpora",
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {bearer_raw}".encode()),
            (b"cookie", f"{auth.SESSION_COOKIE}={cookie_token}".encode()),
        ],
    }
    return Request(scope)


def test_bearer_wins_over_cookie(tmp_path):
    """When BOTH a valid bearer header AND a valid session cookie (for a
    DIFFERENT key) are present, resolve_principal returns the bearer key and
    sets from_cookie=False."""
    _fresh_db(tmp_path)
    settings = _settings(tmp_path)

    with db.SessionLocal() as s:
        bearer_raw = auth.create_key(s, "bearer-key", "write")
        auth.create_key(s, "cookie-key", "read")
        cookie_row = s.query(db.ApiKey).filter_by(name="cookie-key").one()
        # sign a valid, unexpired session cookie for the COOKIE key
        cookie_token = auth.sign_session(cookie_row.id, cookie_row.scope, _SECRET)

    request = _build_request(bearer_raw, cookie_token)

    with db.SessionLocal() as s:
        principal, from_cookie = auth.resolve_principal(request, s, settings)

    # bearer wins: must return the write key, not the read cookie
    assert from_cookie is False
    assert principal is not None
    assert principal.name == "bearer-key"
    assert principal.scope == "write"


def test_cookie_used_when_no_bearer(tmp_path):
    """Baseline: without a bearer header, the session cookie IS the credential
    and from_cookie is True."""
    _fresh_db(tmp_path, "w4b.db")
    settings = _settings(tmp_path, "w4b.db")

    with db.SessionLocal() as s:
        auth.create_key(s, "cookie-only", "read")
        row = s.query(db.ApiKey).filter_by(name="cookie-only").one()
        cookie_token = auth.sign_session(row.id, row.scope, _SECRET)

    # Request with cookie but NO Authorization header
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/corpora",
        "query_string": b"",
        "headers": [
            (b"cookie", f"{auth.SESSION_COOKIE}={cookie_token}".encode()),
        ],
    }
    request = Request(scope)

    with db.SessionLocal() as s:
        principal, from_cookie = auth.resolve_principal(request, s, settings)

    assert from_cookie is True
    assert principal is not None
    assert principal.name == "cookie-only"
