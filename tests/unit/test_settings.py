from madosho_server.settings import Settings, pg_conninfo


def test_pg_conninfo_strips_sqlalchemy_driver():
    assert pg_conninfo("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@db/madosho")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("FILESTORE_DIR", "/data/filestore")
    monkeypatch.setenv("CORPORA_DIR", "/data/corpora")
    s = Settings.from_env()
    assert s.database_url == "postgresql+psycopg://x:y@db/madosho"
    assert s.qdrant_url == "http://qdrant:6333"
    assert s.filestore_dir == "/data/filestore"
    assert s.corpora_dir == "/data/corpora"
