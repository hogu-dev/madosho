import pytest
from madosho_server import auth, db, init_db, users_cli
from madosho_server.settings import Settings


@pytest.fixture()
def udb(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    db.create_all()
    yield


def test_cli_create_uses_getpass_not_argv(udb, monkeypatch, capsys):
    monkeypatch.setattr(users_cli.getpass, "getpass", lambda *a, **k: "typed-secret")
    rc = users_cli.main(["create", "--name", "cliadmin", "--scope", "admin"])
    assert rc == 0
    with db.SessionLocal() as s:
        assert auth.verify_user_credentials(s, "cliadmin", "typed-secret").scope == "admin"


def test_cli_list_and_deactivate(udb, monkeypatch, capsys):
    monkeypatch.setattr(users_cli.getpass, "getpass", lambda *a, **k: "pw")
    users_cli.main(["create", "--name", "a1", "--scope", "admin"])
    users_cli.main(["create", "--name", "a2", "--scope", "admin"])
    assert users_cli.main(["list"]) == 0
    assert "a1" in capsys.readouterr().out
    assert users_cli.main(["deactivate", "--name", "a1"]) == 0
    with db.SessionLocal() as s:
        assert auth.get_user_by_username(s, "a1").is_active is False


def test_cli_create_password_from_env(udb, monkeypatch):
    """Headless: no TTY, password comes from MADOSHO_USER_PASSWORD."""
    monkeypatch.setenv(users_cli.PASSWORD_ENV, "env-secret")
    rc = users_cli.main(["create", "--name", "envuser", "--scope", "write"])
    assert rc == 0
    with db.SessionLocal() as s:
        assert auth.verify_user_credentials(s, "envuser", "env-secret").scope == "write"


def test_cli_create_password_from_stdin(udb, monkeypatch):
    """Headless: --password-stdin reads one line, trailing newline stripped."""
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("piped-secret\n"))
    rc = users_cli.main(["create", "--name", "pipeuser", "--scope", "read",
                         "--password-stdin"])
    assert rc == 0
    with db.SessionLocal() as s:
        assert auth.verify_user_credentials(s, "pipeuser", "piped-secret").scope == "read"


def test_cli_create_rejects_empty_password(udb, monkeypatch):
    monkeypatch.setenv(users_cli.PASSWORD_ENV, "")
    monkeypatch.setattr(users_cli.getpass, "getpass", lambda *a, **k: "")
    assert users_cli.main(["create", "--name", "blank", "--scope", "read"]) == 1
    with db.SessionLocal() as s:
        assert auth.get_user_by_username(s, "blank") is None


def test_cli_reset_password_from_stdin(udb, monkeypatch):
    monkeypatch.setenv(users_cli.PASSWORD_ENV, "orig-pw")
    users_cli.main(["create", "--name", "resetme", "--scope", "read"])
    monkeypatch.delenv(users_cli.PASSWORD_ENV)
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("new-pw\n"))
    rc = users_cli.main(["reset-password", "--name", "resetme", "--password-stdin"])
    assert rc == 0
    with db.SessionLocal() as s:
        assert auth.verify_user_credentials(s, "resetme", "new-pw") is not None


def test_env_seed_creates_admin_only_when_absent(udb, monkeypatch):
    monkeypatch.setenv("MADOSHO_BOOTSTRAP_ADMIN_USER", "seed")
    monkeypatch.setenv("MADOSHO_BOOTSTRAP_ADMIN_PASSWORD", "seed-pw")
    init_db.seed_admin_user(Settings.from_env())
    init_db.seed_admin_user(Settings.from_env())     # idempotent: no duplicate / no error
    with db.SessionLocal() as s:
        assert auth.verify_user_credentials(s, "seed", "seed-pw").scope == "admin"
        assert len(auth.list_users(s)) == 1
