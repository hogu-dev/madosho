import pytest

from madosho_server import auth, db


def _fresh_db(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    db.create_all()


def test_create_key_stores_hash_and_prefix_not_raw(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        raw = auth.create_key(s, "ci-uploader", "write")
    assert raw.startswith("mdsh_")
    with db.SessionLocal() as s:
        row = s.query(db.ApiKey).filter_by(name="ci-uploader").one()
        assert row.key_hash == auth.hash_key(raw)
        assert row.prefix == raw[:12]
        assert row.scope == "write"
        assert row.revoked_at is None
        # the raw secret is nowhere in the stored row
        assert raw not in (row.key_hash, row.prefix)


def test_verify_key_accepts_then_revoke_rejects(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        raw = auth.create_key(s, "analyst", "read")
    with db.SessionLocal() as s:
        assert auth.verify_key(s, raw).name == "analyst"
        assert auth.verify_key(s, "mdsh_not_a_key") is None
        assert auth.verify_key(s, None) is None
    with db.SessionLocal() as s:
        auth.revoke_key(s, "analyst")
    with db.SessionLocal() as s:
        assert auth.verify_key(s, raw) is None          # revoked = inactive


def test_duplicate_name_rejected(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        auth.create_key(s, "dup", "read")
    with db.SessionLocal() as s:
        with pytest.raises(ValueError):
            auth.create_key(s, "dup", "read")


def test_bad_scope_rejected(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        with pytest.raises(ValueError):
            auth.create_key(s, "x", "superuser")


def test_revoke_unknown_name_raises(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        with pytest.raises(ValueError):
            auth.revoke_key(s, "nope")


def test_list_keys_never_exposes_secret(tmp_path):
    _fresh_db(tmp_path)
    with db.SessionLocal() as s:
        raw = auth.create_key(s, "k", "admin")
    with db.SessionLocal() as s:
        rows = auth.list_keys(s)
        assert [r.name for r in rows] == ["k"]
        assert raw not in (rows[0].key_hash, rows[0].prefix)


def test_scope_allows_ordering():
    assert auth.scope_allows("admin", "write")
    assert auth.scope_allows("admin", "read")
    assert auth.scope_allows("write", "read")
    assert auth.scope_allows("write", "write")
    assert not auth.scope_allows("read", "write")
    assert not auth.scope_allows("write", "admin")


from madosho_server.settings import Settings


def test_auth_enabled_flag(monkeypatch):
    monkeypatch.delenv("MADOSHO_AUTH_ENABLED", raising=False)
    assert Settings.from_env().auth_enabled is True         # ships ON by default
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    assert Settings.from_env().auth_enabled is True
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "TRUE")
    assert Settings.from_env().auth_enabled is True
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "false")
    assert Settings.from_env().auth_enabled is False


from fastapi.testclient import TestClient


def _api_client(tmp_path, monkeypatch, *, auth_on):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1" if auth_on else "0")
    import procrastinate
    from madosho_server import api, tasks
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    return api


def _seed_keys():
    with db.SessionLocal() as s:
        return {
            "read": auth.create_key(s, "r", "read"),
            "write": auth.create_key(s, "w", "write"),
            "admin": auth.create_key(s, "a", "admin"),
        }


def test_flag_off_leaves_endpoints_open(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=False)
    with TestClient(api.app) as client:
        assert client.get("/corpora").status_code == 200
        assert client.post("/corpora", json={"name": "open"}).status_code == 201


def test_absent_and_invalid_key_rejected(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        r = client.get("/corpora")
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"] == "Bearer"
        r = client.get("/corpora", headers={"Authorization": "Bearer mdsh_garbage"})
        assert r.status_code == 401


def test_read_key_reads_but_cannot_write(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        keys = _seed_keys()
        h = {"Authorization": f"Bearer {keys['read']}"}
        assert client.get("/corpora", headers=h).status_code == 200
        r = client.post("/corpora", json={"name": "x"}, headers=h)
        assert r.status_code == 403
        assert r.headers["WWW-Authenticate"] == 'Bearer error="insufficient_scope"'


def test_write_and_admin_keys_can_write(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        keys = _seed_keys()
        for label, name in (("write", "wc"), ("admin", "ac")):
            h = {"Authorization": f"Bearer {keys[label]}"}
            assert client.get("/corpora", headers=h).status_code == 200      # write/admin imply read
            assert client.post("/corpora", json={"name": name}, headers=h).status_code == 201


def test_revoked_key_rejected_immediately(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        keys = _seed_keys()
        h = {"Authorization": f"Bearer {keys['read']}"}
        assert client.get("/corpora", headers=h).status_code == 200
        with db.SessionLocal() as s:
            auth.revoke_key(s, "r")
        assert client.get("/corpora", headers=h).status_code == 401


def test_health_open_with_flag_on(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200


def _query_client(tmp_path, monkeypatch, *, auth_on):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'q.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1" if auth_on else "0")
    from madosho_server import query_api
    return query_api


def test_query_plane_requires_key(tmp_path, monkeypatch):
    query_api = _query_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(query_api.app) as client:
        assert client.get("/health").status_code == 200            # open
        assert client.get("/v1/models").status_code == 401         # no key
        # POST /query is a READ despite the verb: a read key must get PAST auth
        # (the request may then 422 on body validation, but never 401/403).
        with db.SessionLocal() as s:
            read_key = auth.create_key(s, "qr", "read")
        h = {"Authorization": f"Bearer {read_key}"}
        assert client.get("/v1/models", headers=h).status_code == 200
        # POST /query with a read key must get PAST auth (may then 422 on the empty body,
        # but never 401/403). The no-key GET above already proves the plane is gated; we
        # avoid asserting a status on the no-key POST because app-dependency-vs-body
        # ordering could surface 422 instead of 401.
        assert client.post("/query", json={}, headers=h).status_code not in (401, 403)


def test_query_plane_open_when_flag_off(tmp_path, monkeypatch):
    query_api = _query_client(tmp_path, monkeypatch, auth_on=False)
    with TestClient(query_api.app) as client:
        assert client.get("/v1/models").status_code == 200


from unittest.mock import MagicMock


def test_last_used_set_after_authenticated_request(tmp_path, monkeypatch):
    api = _api_client(tmp_path, monkeypatch, auth_on=True)
    with TestClient(api.app) as client:
        keys = _seed_keys()
        with db.SessionLocal() as s:
            assert s.query(db.ApiKey).filter_by(name="r").one().last_used_at is None
        assert client.get("/corpora",
                           headers={"Authorization": f"Bearer {keys['read']}"}).status_code == 200
        with db.SessionLocal() as s:
            assert s.query(db.ApiKey).filter_by(name="r").one().last_used_at is not None


def test_touch_last_used_swallows_errors():
    session = MagicMock()
    session.commit.side_effect = RuntimeError("db down")
    # must NOT raise - a failed stamp can never break the request
    auth.touch_last_used(session, MagicMock())
    session.rollback.assert_called_once()


from madosho_server import keys_cli


def _cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def test_keys_cli_create_list_revoke_roundtrip(tmp_path, monkeypatch, capsys):
    _cli_env(tmp_path, monkeypatch)

    assert keys_cli.main(["create", "--name", "ci", "--scope", "write"]) == 0
    raw = capsys.readouterr().out
    assert "mdsh_" in raw                                   # the value is printed once

    # the printed value really works, and only its hash is stored
    token = next(t for t in raw.split() if t.startswith("mdsh_"))
    with db.SessionLocal() as s:
        row = s.query(db.ApiKey).filter_by(name="ci").one()
        assert row.key_hash == auth.hash_key(token)

    assert keys_cli.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "ci" in listed and row.prefix in listed
    assert token not in listed                              # list never shows the secret

    assert keys_cli.main(["revoke", "ci"]) == 0
    with db.SessionLocal() as s:
        assert auth.verify_key(s, token) is None            # revoked


def test_keys_cli_duplicate_name_exits_nonzero(tmp_path, monkeypatch, capsys):
    _cli_env(tmp_path, monkeypatch)
    assert keys_cli.main(["create", "--name", "dup", "--scope", "read"]) == 0
    capsys.readouterr()
    assert keys_cli.main(["create", "--name", "dup", "--scope", "read"]) == 1


import ast
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[2]


def test_auth_probe_is_ascii_stdlib_and_compiles():
    src = (_REPO / "examples" / "auth" / "probe.py").read_text()
    src.encode("ascii")                                    # ASCII-only (user rule)
    tree = ast.parse(src)                                  # valid Python
    imported = {n.module.split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {a.name.split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    stdlib = {"argparse", "json", "os", "sys", "urllib", "http"}
    assert imported <= stdlib, f"probe must be stdlib-only, found {imported - stdlib}"


def test_auth_doc_exists():
    assert (_REPO / "docs" / "AUTH.md").exists()
