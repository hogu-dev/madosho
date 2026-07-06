import hmac
import hashlib

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from madosho_server import auth as auth_mod, db
from madosho_server.api import app
from madosho_server.settings import Settings


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

class _W5Db:
    """Thin helper exposed to tests: .create(name, scope) -> raw key,
    .row(name) -> ApiKey (for later tasks that need to inspect the row)."""

    def create(self, name: str, scope: str) -> str:
        with db.SessionLocal() as s:
            return auth_mod.create_key(s, name, scope)

    def row(self, name: str):
        with db.SessionLocal() as s:
            return s.query(db.ApiKey).filter_by(name=name).one()


@pytest.fixture()
def w5_db(tmp_path):
    """Configure a fresh per-test SQLite db, create all tables, yield _W5Db helper."""
    db.configure_engine(f"sqlite:///{tmp_path / 'w5.db'}")
    db.create_all()
    yield _W5Db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_app():
    app = FastAPI()

    @app.get("/probe")
    def probe(_=Depends(auth_mod.require_admin)):
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# require_admin tests
# ---------------------------------------------------------------------------

def test_require_admin_allows_admin_bearer(w5_db):
    admin = w5_db.create("a-admin", "admin")
    c = TestClient(_probe_app())
    r = c.get("/probe", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200


def test_require_admin_rejects_write_scope(w5_db):
    writer = w5_db.create("a-writer", "write")
    c = TestClient(_probe_app())
    r = c.get("/probe", headers={"Authorization": f"Bearer {writer}"})
    assert r.status_code == 403


def test_require_admin_rejects_no_credentials(w5_db):
    c = TestClient(_probe_app())
    assert c.get("/probe").status_code == 401


def test_require_admin_enforces_even_when_flag_off(w5_db, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "0")           # flag OFF
    c = TestClient(_probe_app())
    assert c.get("/probe").status_code == 401                 # door still locked
    admin = w5_db.create("a-admin2", "admin")
    assert c.get("/probe", headers={"Authorization": f"Bearer {admin}"}).status_code == 200


# ---------------------------------------------------------------------------
# exp-coercion regression (Step 6 - added with tidy-ups)
# ---------------------------------------------------------------------------

def test_session_token_with_garbage_exp_is_rejected_not_raised():
    secret = "s"
    body = auth_mod._b64u(b'{"kid":1,"scope":"admin","exp":"not-a-number"}')
    sig = auth_mod._b64u(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    assert auth_mod.verify_session_token(f"{body}.{sig}", secret) is None


# ---------------------------------------------------------------------------
# /auth/keys POST + GET (Task 2)
# ---------------------------------------------------------------------------

def test_mint_returns_raw_key_once_and_stores_only_hash(w5_db):
    admin = w5_db.create("root", "admin")
    c = TestClient(app)
    r = c.post("/auth/keys", json={"name": "ci", "scope": "write"},
               headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "ci" and body["scope"] == "write"
    assert body["prefix"] == body["key"][:12]
    # the raw key actually authenticates and its hash is what is stored
    assert auth_mod.hash_key(body["key"]) == w5_db.row("ci").key_hash
    assert "key_hash" not in body


def test_mint_rejected_for_non_admin(w5_db):
    writer = w5_db.create("w", "write")
    c = TestClient(app)
    r = c.post("/auth/keys", json={"name": "x", "scope": "read"},
               headers={"Authorization": f"Bearer {writer}"})
    assert r.status_code == 403


def test_mint_duplicate_name_409(w5_db):
    admin = w5_db.create("root", "admin")
    c = TestClient(app)
    h = {"Authorization": f"Bearer {admin}"}
    c.post("/auth/keys", json={"name": "dup", "scope": "read"}, headers=h)
    r = c.post("/auth/keys", json={"name": "dup", "scope": "read"}, headers=h)
    assert r.status_code == 409


def test_mint_bad_scope_422(w5_db):
    admin = w5_db.create("root", "admin")
    c = TestClient(app)
    r = c.post("/auth/keys", json={"name": "bad", "scope": "superuser"},
               headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 422


def test_list_returns_prefix_only_never_hash(w5_db):
    admin = w5_db.create("root", "admin")
    c = TestClient(app)
    r = c.get("/auth/keys", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200
    rows = r.json()
    assert any(row["name"] == "root" for row in rows)
    for row in rows:
        assert set(row) == {"name", "prefix", "scope", "created_at", "last_used_at", "revoked_at"}
        assert "key_hash" not in row and "key" not in row


def test_keys_endpoints_locked_when_flag_off(w5_db, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "0")
    c = TestClient(app)
    assert c.get("/auth/keys").status_code == 401            # never open
    assert c.post("/auth/keys", json={"name": "n", "scope": "read"}).status_code == 401


# ---------------------------------------------------------------------------
# /auth/keys DELETE (Task 3)
# ---------------------------------------------------------------------------

def test_revoke_returns_204_and_key_stops_working(w5_db):
    admin = w5_db.create("root", "admin")
    victim = w5_db.create("temp", "write")
    c = TestClient(app)
    h = {"Authorization": f"Bearer {admin}"}
    assert c.delete("/auth/keys/temp", headers=h).status_code == 204
    # the revoked key no longer authenticates
    assert c.get("/auth/keys", headers={"Authorization": f"Bearer {victim}"}).status_code in (401, 403)

def test_revoke_unknown_name_404(w5_db):
    admin = w5_db.create("root", "admin")
    c = TestClient(app)
    assert c.delete("/auth/keys/ghost", headers={"Authorization": f"Bearer {admin}"}).status_code == 404

def test_cannot_revoke_last_admin(w5_db):
    admin = w5_db.create("only-admin", "admin")
    c = TestClient(app)
    r = c.delete("/auth/keys/only-admin", headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 409

def test_can_revoke_admin_when_another_admin_exists(w5_db):
    a1 = w5_db.create("admin-1", "admin")
    w5_db.create("admin-2", "admin")
    c = TestClient(app)
    assert c.delete("/auth/keys/admin-1", headers={"Authorization": f"Bearer {a1}"}).status_code == 204


# ---------------------------------------------------------------------------
# Flag-ON composition: control_auth + require_admin
# ---------------------------------------------------------------------------

@pytest.mark.authed
def test_flag_on_composition_control_auth_and_require_admin(w5_db):
    """Prove flag-ON composition: control_auth (app-level, flag-gated) and
    require_admin (route-level, always-on) both execute on /auth/keys routes.

    False-green guard: asserting 403 alone is not enough -- require_admin in
    isolation (flag OFF) also returns 403, so a broken flag would still pass.
    Two anchors make this test genuinely flag-ON specific:

    1. Direct check: Settings.from_env().auth_enabled is True.
    2. Behavioral check: GET /corpora with no credentials returns 401 (data
       plane gated). With flag OFF that same request returns 200/other, never
       401 from control_auth.

    Then the composition assertions confirm each scope combination:
    - no credentials             -> 401  (unauthenticated)
    - read key  on GET           -> 403  (control_auth passes; require_admin rejects)
    - write key on POST          -> 403  (control_auth passes; require_admin rejects)
    - admin key on GET           -> 200  (both pass)
    """
    # Anchor 1: conftest sets MADOSHO_AUTH_ENABLED=1 for @pytest.mark.authed.
    assert Settings.from_env().auth_enabled is True

    read_key = w5_db.create("comp-reader", "read")
    write_key = w5_db.create("comp-writer", "write")
    admin_key = w5_db.create("comp-admin", "admin")

    c = TestClient(app)

    # Anchor 2: data-plane route must be gated (would be open with flag OFF).
    assert c.get("/corpora").status_code == 401

    # Unauthenticated request to /auth/keys -> 401.
    assert c.get("/auth/keys").status_code == 401

    # read key: control_auth satisfied (GET requires "read"), require_admin not -> 403.
    r = c.get("/auth/keys", headers={"Authorization": f"Bearer {read_key}"})
    assert r.status_code == 403

    # write key: control_auth satisfied (POST requires "write"), require_admin not -> 403.
    r = c.post("/auth/keys", json={"name": "nope", "scope": "read"},
               headers={"Authorization": f"Bearer {write_key}"})
    assert r.status_code == 403

    # admin key: both control_auth and require_admin satisfied -> 200.
    r = c.get("/auth/keys", headers={"Authorization": f"Bearer {admin_key}"})
    assert r.status_code == 200
