import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from madosho_server import auth, db
from madosho_server.api import app
from madosho_server.settings import Settings


def test_password_hash_roundtrips_and_is_salted():
    h1 = auth.hash_password("hunter2")
    h2 = auth.hash_password("hunter2")
    assert h1 != h2                      # random per-hash salt
    assert h1.startswith("scrypt$")
    assert auth.verify_password("hunter2", h1)
    assert auth.verify_password("hunter2", h2)


def test_password_verify_rejects_wrong_and_garbage():
    h = auth.hash_password("correct horse")
    assert not auth.verify_password("battery staple", h)
    assert not auth.verify_password("correct horse", "not-a-hash")
    assert not auth.verify_password("correct horse", "scrypt$bad$fields")


@pytest.fixture()
def udb(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'users.db'}")
    db.create_all()
    yield


def _session():
    return db.SessionLocal()


def test_create_user_stores_hash_not_plaintext(udb):
    with _session() as s:
        u = auth.create_user(s, "alice", "pw-alice", "write")
        assert u.username == "alice" and u.scope == "write" and u.is_active is True
        assert "pw-alice" not in u.password_hash
        assert auth.verify_password("pw-alice", u.password_hash)


def test_create_user_rejects_bad_scope_and_duplicate(udb):
    with _session() as s:
        auth.create_user(s, "bob", "pw", "read")
        with pytest.raises(ValueError):
            auth.create_user(s, "bob", "pw2", "read")       # duplicate username
        with pytest.raises(ValueError):
            auth.create_user(s, "carol", "pw", "root")      # bad scope


def test_verify_user_credentials(udb):
    with _session() as s:
        auth.create_user(s, "dave", "secret", "read")
    with _session() as s:
        assert auth.verify_user_credentials(s, "dave", "secret").username == "dave"
        assert auth.verify_user_credentials(s, "dave", "wrong") is None
        assert auth.verify_user_credentials(s, "ghost", "secret") is None


def test_deactivate_user_blocks_login(udb):
    with _session() as s:
        u = auth.create_user(s, "eve", "pw", "write")
        auth.deactivate_user(s, u)
    with _session() as s:
        assert auth.verify_user_credentials(s, "eve", "pw") is None    # inactive


def test_cannot_deactivate_last_active_admin(udb):
    with _session() as s:
        a1 = auth.create_user(s, "admin1", "pw", "admin")
        with pytest.raises(ValueError):
            auth.deactivate_user(s, a1)                     # sole admin
        auth.create_user(s, "admin2", "pw", "admin")
    with _session() as s:
        a1 = auth.get_user_by_username(s, "admin1")
        auth.deactivate_user(s, a1)                         # ok: another admin exists
        assert auth.get_user_by_username(s, "admin1").is_active is False


def test_set_password_changes_credentials(udb):
    with _session() as s:
        u = auth.create_user(s, "frank", "old", "read")
        auth.set_password(s, u, "new")
    with _session() as s:
        assert auth.verify_user_credentials(s, "frank", "new").username == "frank"
        assert auth.verify_user_credentials(s, "frank", "old") is None


def _scope_app():
    app = FastAPI()

    @app.get("/who")
    def who(p=Depends(auth.current_principal)):
        return {"kind": p.kind, "scope": p.scope, "name": p.name}

    return app


def test_user_session_cookie_resolves_and_enforces(udb, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    with _session() as s:
        u = auth.create_user(s, "ada", "pw", "write")
        uid = u.id
    secret = auth.session_secret(Settings.from_env())
    token = auth.sign_session_user(uid, "write", secret)
    c = TestClient(_scope_app())
    c.cookies.set(auth.SESSION_COOKIE, token)       # set on the client, not per-request (httpx)
    r = c.get("/who")
    assert r.status_code == 200
    assert r.json() == {"kind": "user", "scope": "write", "name": "ada"}


def test_deactivated_user_cookie_is_rejected(udb):
    with _session() as s:
        u = auth.create_user(s, "lou", "pw", "write")
        uid = u.id
        auth.deactivate_user(s, u)
    secret = auth.session_secret(Settings.from_env())
    token = auth.sign_session_user(uid, "write", secret)
    c = TestClient(_scope_app())
    c.cookies.set(auth.SESSION_COOKIE, token)       # set on the client, not per-request (httpx)
    assert c.get("/who").status_code == 401


def test_existing_key_bearer_still_resolves(udb):
    with _session() as s:
        raw = auth.create_key(s, "k-admin", "admin")
    c = TestClient(_scope_app())
    r = c.get("/who", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200 and r.json()["kind"] == "key" and r.json()["name"] == "k-admin"


def test_login_with_username_password_sets_user_session(udb, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    with _session() as s:
        auth.create_user(s, "grace", "pw-grace", "write")
    c = TestClient(app)
    r = c.post("/auth/login", json={"username": "grace", "password": "pw-grace"})
    assert r.status_code == 200
    assert r.json() == {"scope": "write", "name": "grace", "kind": "user"}
    # cookie now authorizes a write on the control plane
    assert c.get("/auth/me").json()["kind"] == "user"
    with _session() as s:
        assert auth.get_user_by_username(s, "grace").last_login_at is not None


def test_login_bad_password_401(udb):
    with _session() as s:
        auth.create_user(s, "heidi", "right", "read")
    c = TestClient(app)
    assert c.post("/auth/login", json={"username": "heidi", "password": "wrong"}).status_code == 401


def test_login_with_key_still_works(udb):
    with _session() as s:
        raw = auth.create_key(s, "k1", "admin")
    c = TestClient(app)
    r = c.post("/auth/login", json={"key": raw})
    assert r.status_code == 200 and r.json()["name"] == "k1"


def test_login_empty_body_422(udb):
    c = TestClient(app)
    assert c.post("/auth/login", json={}).status_code == 422


# ---------------------------------------------------------------------------
# Task 5: admin user CRUD + self change-password endpoints
# ---------------------------------------------------------------------------

def _admin_client(udb_username="root"):
    with _session() as s:
        raw = auth.create_key(s, "ep-admin", "admin")
    return TestClient(app), {"Authorization": f"Bearer {raw}"}


def test_create_and_list_user_never_leaks_hash(udb):
    c, h = _admin_client()
    r = c.post("/auth/users", json={"username": "ivan", "scope": "read", "password": "pw"}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "ivan" and body["scope"] == "read" and body["is_active"] is True
    assert "password_hash" not in body and "password" not in body
    rows = c.get("/auth/users", headers=h).json()
    assert any(u["username"] == "ivan" for u in rows)
    for u in rows:
        assert "password_hash" not in u


def test_user_endpoints_require_admin(udb):
    with _session() as s:
        writer = auth.create_key(s, "w", "write")
    c = TestClient(app)
    h = {"Authorization": f"Bearer {writer}"}
    assert c.get("/auth/users", headers=h).status_code == 403
    assert c.post("/auth/users", json={"username": "x", "scope": "read", "password": "p"},
                  headers=h).status_code == 403
    assert c.get("/auth/users").status_code == 401


def test_create_duplicate_username_409_bad_scope_422(udb):
    c, h = _admin_client()
    c.post("/auth/users", json={"username": "dup", "scope": "read", "password": "p"}, headers=h)
    assert c.post("/auth/users", json={"username": "dup", "scope": "read", "password": "p"},
                  headers=h).status_code == 409
    assert c.post("/auth/users", json={"username": "bs", "scope": "root", "password": "p"},
                  headers=h).status_code == 422


def test_deactivate_user_204_and_404(udb):
    c, h = _admin_client()
    uid = c.post("/auth/users", json={"username": "tmp", "scope": "write", "password": "p"},
                 headers=h).json()["id"]
    assert c.delete(f"/auth/users/{uid}", headers=h).status_code == 204
    assert c.delete("/auth/users/999999", headers=h).status_code == 404


def test_cannot_deactivate_last_admin_user_409(udb):
    c, h = _admin_client()
    uid = c.post("/auth/users", json={"username": "onlyadmin", "scope": "admin", "password": "p"},
                 headers=h).json()["id"]
    assert c.delete(f"/auth/users/{uid}", headers=h).status_code == 409


def test_admin_reset_password(udb):
    c, h = _admin_client()
    uid = c.post("/auth/users", json={"username": "reset-me", "scope": "read", "password": "old"},
                 headers=h).json()["id"]
    assert c.post(f"/auth/users/{uid}/password", json={"new_password": "new"},
                  headers=h).status_code == 204
    assert c.post("/auth/login", json={"username": "reset-me", "password": "new"}).status_code == 200


def test_self_change_password_requires_current(udb, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    with _session() as s:
        auth.create_user(s, "self", "old", "write")
    c = TestClient(app)
    c.post("/auth/login", json={"username": "self", "password": "old"})   # sets cookie
    assert c.post("/auth/me/password",
                  json={"current_password": "nope", "new_password": "x"}).status_code == 403
    assert c.post("/auth/me/password",
                  json={"current_password": "old", "new_password": "brandnew"}).status_code == 204
    c.post("/auth/logout")
    assert c.post("/auth/login", json={"username": "self", "password": "brandnew"}).status_code == 200


def test_self_change_password_rejected_for_key_principal(udb):
    with _session() as s:
        raw = auth.create_key(s, "keyonly", "admin")
    c = TestClient(app)
    r = c.post("/auth/me/password", json={"current_password": "a", "new_password": "b"},
               headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 400


@pytest.mark.authed
def test_flag_on_user_management_composition(udb, monkeypatch):
    """Flag-ON pin: /auth/users is admin-gated regardless of the data-plane flag,
    and a user session created via /auth/login carries its scope through the gates."""
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    assert Settings.from_env().auth_enabled is True       # conftest sets it for @authed
    with _session() as s:
        admin_key = auth.create_key(s, "comp-admin", "admin")
        auth.create_user(s, "comp-writer", "pw", "write")
    c = TestClient(app)

    # data-plane is gated (would be open with the flag off)
    assert c.get("/corpora").status_code == 401
    # /auth/users requires admin
    assert c.get("/auth/users").status_code == 401
    assert c.get("/auth/users", headers={"Authorization": f"Bearer {admin_key}"}).status_code == 200

    # a write user logs in, gets a session, can read+write data but NOT manage users
    assert c.post("/auth/login", json={"username": "comp-writer", "password": "pw"}).status_code == 200
    assert c.get("/corpora").status_code == 200            # read ok via cookie
    assert c.get("/auth/users").status_code == 403         # not admin


def test_read_user_can_change_own_password(udb, monkeypatch):
    """Regression: a read-scoped user must reach /auth/me/password despite control_auth
    blocking POSTs from non-write principals. Fix: /auth/me/password in _AUTH_OPEN so
    the endpoint's own current_principal gate (always-on: requires auth) is the sole gatekeeper.
    Without the fix this returns 403 instead of 204."""
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    monkeypatch.setenv("MADOSHO_COOKIE_INSECURE", "1")
    with _session() as s:
        auth.create_user(s, "reader", "old", "read")
    c = TestClient(app)
    r = c.post("/auth/login", json={"username": "reader", "password": "old"})
    assert r.status_code == 200
    # change password: was 403 (control_auth blocked read-scope POST) before the fix
    r = c.post("/auth/me/password", json={"current_password": "old", "new_password": "new"})
    assert r.status_code == 204, f"expected 204 but got {r.status_code} ({r.text})"
    # verify the new password works
    c.post("/auth/logout")
    assert c.post("/auth/login", json={"username": "reader", "password": "new"}).status_code == 200
