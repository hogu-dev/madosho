"""Document provenance: the origin columns, the origin_label helper, and the
_ingest_bytes threading that stamps a generated document on first creation."""
from madosho_server import api, db
from madosho_server.provenance import origin_label
from madosho_server.settings import Settings


def test_origin_label_generated_with_goal_and_version():
    assert origin_label("generated", {"goal": "find_vuln", "version": 2}) == \
        "[generated: find_vuln v2]"


def test_origin_label_generated_goal_only():
    # version missing -> fall back to the bare goal name (no "vNone")
    assert origin_label("generated", {"goal": "find_vuln"}) == \
        "[generated: find_vuln]"


def test_origin_label_generated_no_meta():
    assert origin_label("generated", None) == "[generated: alchemy]"


def test_origin_label_source_is_empty():
    # source docs render nothing, so normal citations/rows are byte-identical
    assert origin_label("source", {"goal": "x", "version": 1}) == ""


def test_document_origin_defaults_to_source(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'origin.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        d = db.Document(filename="a.pdf", content_hash="h",
                        file_uri="u", mimetype="application/pdf", status="indexed")
        s.add(d); s.commit(); did = d.id
    with db.SessionLocal() as s:
        got = s.get(db.Document, did)
        assert got.origin == "source"
        assert got.origin_meta == {}
        assert got.origin_label == ""


def _fs_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))


def test_ingest_bytes_stamps_generated_origin(tmp_path, monkeypatch):
    _fs_env(tmp_path, monkeypatch)
    db.configure_engine(f"sqlite:///{tmp_path/'ib.db'}")
    db.create_all()
    noop = lambda *a, **k: None      # enqueue seams are irrelevant here
    with db.SessionLocal() as s:
        doc = api._ingest_bytes(
            s, Settings.from_env(), noop, noop,
            content=b"# gen\n\nbody", filename="find_vuln-v2.md",
            mimetype="text/markdown", corpus_id=None,
            parser=None, chunker=None, embedder=None, name=None, options=None,
            origin="generated",
            origin_meta={"goal": "find_vuln", "version": 2, "run_id": 9})
        assert doc.origin == "generated"
        assert doc.origin_meta["goal"] == "find_vuln"
        assert doc.origin_label == "[generated: find_vuln v2]"


def test_ingest_bytes_defaults_to_source(tmp_path, monkeypatch):
    _fs_env(tmp_path, monkeypatch)
    db.configure_engine(f"sqlite:///{tmp_path/'ib2.db'}")
    db.create_all()
    noop = lambda *a, **k: None
    with db.SessionLocal() as s:
        doc = api._ingest_bytes(
            s, Settings.from_env(), noop, noop,
            content=b"plain source bytes", filename="s.txt",
            mimetype="text/plain", corpus_id=None,
            parser=None, chunker=None, embedder=None, name=None, options=None)
        assert doc.origin == "source"
        assert doc.origin_label == ""
