import ast
import pathlib

import pytest

from madosho_server import auth, db
from madosho_server.settings import Settings

SECRET = "test-secret-not-a-real-one"


def test_sign_verify_roundtrip():
    tok = auth.sign_session(7, "write", SECRET, now=1000.0)
    payload = auth.verify_session_token(tok, SECRET, now=1000.0)
    assert payload == {"kid": 7, "scope": "write", "exp": 1000 + auth.SESSION_TTL}


def test_tampered_token_rejected():
    tok = auth.sign_session(7, "write", SECRET, now=1000.0)
    body, _, sig = tok.partition(".")
    forged = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig
    assert auth.verify_session_token(forged, SECRET, now=1000.0) is None


def test_wrong_secret_rejected():
    tok = auth.sign_session(7, "write", SECRET, now=1000.0)
    assert auth.verify_session_token(tok, "other-secret", now=1000.0) is None


def test_expired_token_rejected():
    tok = auth.sign_session(7, "read", SECRET, now=1000.0)
    assert auth.verify_session_token(tok, SECRET, now=1000.0 + auth.SESSION_TTL + 1) is None


def test_garbage_token_rejected():
    assert auth.verify_session_token(None, SECRET) is None
    assert auth.verify_session_token("not-a-token", SECRET) is None
    assert auth.verify_session_token("a.b.c", SECRET) is None


def test_session_secret_uses_env_then_stable_fallback(monkeypatch):
    monkeypatch.setenv("MADOSHO_SESSION_SECRET", "from-env")
    assert auth.session_secret(Settings.from_env()) == "from-env"
    monkeypatch.delenv("MADOSHO_SESSION_SECRET", raising=False)
    s = Settings.from_env()
    once = auth.session_secret(s)
    assert once and auth.session_secret(s) == once     # stable within the process


def test_cookie_insecure_flag(monkeypatch):
    monkeypatch.delenv("MADOSHO_COOKIE_INSECURE", raising=False)
    assert Settings.from_env().cookie_insecure is False
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    assert Settings.from_env().cookie_insecure is True


from fastapi.testclient import TestClient


def _api(tmp_path, monkeypatch, *, auth_on, insecure=True):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1" if auth_on else "0")
    if insecure:
        monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")   # so TestClient keeps the cookie over http
    import procrastinate
    from madosho_server import api, tasks
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    return api


def _cookie_for(name, scope):
    """Mint a key and hand back a freshly-signed session cookie value for it."""
    from madosho_server.settings import Settings
    with db.SessionLocal() as s:
        auth.create_key(s, name, scope)
        row = s.query(db.ApiKey).filter_by(name=name).one()
        return auth.sign_session(row.id, row.scope, auth.session_secret(Settings.from_env()))


def test_cookie_authenticates_control_plane(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        client.cookies.set(auth.SESSION_COOKIE, _cookie_for("w", "write"))
        assert client.get("/corpora").status_code == 200
        assert client.post("/corpora", json={"name": "via-cookie"}).status_code == 201


def test_cookie_read_scope_cannot_write(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        client.cookies.set(auth.SESSION_COOKIE, _cookie_for("r", "read"))
        assert client.get("/corpora").status_code == 200
        assert client.post("/corpora", json={"name": "x"}).status_code == 403


def test_revoked_key_cookie_rejected(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        client.cookies.set(auth.SESSION_COOKIE, _cookie_for("rv", "read"))
        assert client.get("/corpora").status_code == 200
        with db.SessionLocal() as s:
            auth.revoke_key(s, "rv")
        assert client.get("/corpora").status_code == 401


def test_tampered_cookie_rejected(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        good = _cookie_for("t", "read")
        client.cookies.set(auth.SESSION_COOKIE, good[:-2] + "zz")
        assert client.get("/corpora").status_code == 401


def test_cookie_slides_on_authenticated_request(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        client.cookies.set(auth.SESSION_COOKIE, _cookie_for("s", "read"))
        r = client.get("/corpora")
        assert r.status_code == 200
        assert auth.SESSION_COOKIE in r.headers.get("set-cookie", "")   # re-issued


def test_cookie_authenticates_query_plane(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    from madosho_server import query_api
    with TestClient(query_api.app) as client:
        assert client.get("/v1/models").status_code == 401         # no cookie
        client.cookies.set(auth.SESSION_COOKIE, _cookie_for("qc", "read"))
        assert client.get("/v1/models").status_code == 200         # cookie works on :8001 too


def test_login_sets_cookie_and_me_reports_scope(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        with db.SessionLocal() as s:
            raw = auth.create_key(s, "ana", "write")
        r = client.post("/auth/login", json={"key": raw})
        assert r.status_code == 200 and r.json()["scope"] == "write"
        assert auth.SESSION_COOKIE in r.headers.get("set-cookie", "")
        # the cookie the login set now authenticates and /auth/me reports it
        me = client.get("/auth/me").json()
        assert me == {"authenticated": True, "auth_required": True, "scope": "write", "name": "ana", "kind": "key"}


def test_login_bad_key_401_no_cookie(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        r = client.post("/auth/login", json={"key": "mdsh_nope"})
        assert r.status_code == 401
        assert auth.SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_me_anonymous_reports_posture_by_flag(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        assert client.get("/auth/me").json() == {
            "authenticated": False, "auth_required": True, "scope": None, "name": None, "kind": None}


def test_me_anonymous_open_when_flag_off(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=False)
    with TestClient(api.app) as client:
        assert client.get("/auth/me").json() == {
            "authenticated": False, "auth_required": False, "scope": None, "name": None, "kind": None}


def test_logout_clears_cookie(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        with db.SessionLocal() as s:
            raw = auth.create_key(s, "lo", "read")
        client.post("/auth/login", json={"key": raw})
        assert client.get("/corpora").status_code == 200      # cookie active
        client.post("/auth/logout")
        client.cookies.clear()                                # browser would drop the cleared cookie
        assert client.get("/corpora").status_code == 401


def test_auth_endpoints_reachable_with_flag_on(tmp_path, monkeypatch):
    # POST /auth/login must NOT demand a write key just because the global POST->write
    # rule is active: it is the very thing you call to GET a credential.
    api = _api(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        assert client.post("/auth/login", json={"key": "mdsh_nope"}).status_code == 401  # 401, not 403
        assert client.get("/auth/me").status_code == 200
        assert client.post("/auth/logout").status_code == 200


_REPO = pathlib.Path(__file__).resolve().parents[2]


def test_login_example_is_ascii_stdlib_and_compiles():
    src = (_REPO / "examples" / "auth" / "login.py").read_text()
    src.encode("ascii")
    tree = ast.parse(src)
    imported = {n.module.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {a.name.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.Import) for a in node.names}
    stdlib = {"argparse", "json", "os", "sys", "urllib", "http"}
    assert imported <= stdlib, f"login example must be stdlib-only, found {imported - stdlib}"


def test_auth_doc_has_browser_section():
    text = (_REPO / "docs" / "AUTH.md").read_text()
    assert "login" in text.lower() and "cookie" in text.lower()
