import ast
import io
import json
import pathlib
from unittest import mock

import pytest

from madosho_cli import http
from madosho_cli import core
from madosho_cli import manifest as _manifest
from madosho_cli import main as cli_main


def test_auth_header_present_only_when_env_set(monkeypatch):
    monkeypatch.delenv("MADOSHO_API_KEY", raising=False)
    assert http._auth_headers() == {}
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_testkey")
    assert http._auth_headers() == {"Authorization": "Bearer mdsh_testkey"}


def test_get_post_attach_auth_header(monkeypatch):
    monkeypatch.setenv("MADOSHO_API_KEY", "mdsh_testkey")
    seen = {}

    def fake_read(req):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return {"ok": True}

    monkeypatch.setattr(http, "_read", fake_read)
    http.get_json("http://x/y")
    assert seen["headers"].get("authorization") == "Bearer mdsh_testkey"
    http.post_json("http://x/y", {"a": 1})
    assert seen["headers"].get("authorization") == "Bearer mdsh_testkey"


def test_post_multipart_builds_parseable_body(monkeypatch, tmp_path):
    f = tmp_path / "nda.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    captured = {}

    def fake_read(req):
        captured["ctype"] = req.get_header("Content-type")
        captured["body"] = req.data
        return {"id": 1, "status": "received"}

    monkeypatch.setattr(http, "_read", fake_read)
    out = http.post_multipart("http://x/documents",
                              {"parser": "docling", "chunker": None}, str(f))
    assert out["id"] == 1
    assert "multipart/form-data; boundary=" in captured["ctype"]
    body = captured["body"]
    assert b'name="parser"' in body and b"docling" in body
    assert b'name="chunker"' not in body            # None field dropped
    assert b'filename="nda.pdf"' in body and b"%PDF-1.4 hello" in body


def test_create_corpus_posts_to_corpora(monkeypatch):
    calls = []
    monkeypatch.setattr(core.http, "post_json",
                        lambda url, payload: calls.append((url, payload)) or {"id": 7, "name": payload["name"]})
    out = core.create_corpus("contracts")
    assert out == {"id": 7, "name": "contracts"}
    assert calls[0][0].endswith("/corpora") and calls[0][1] == {"name": "contracts"}


def test_upload_document_path_no_corpus_uses_multipart_library(monkeypatch):
    seen = {}
    monkeypatch.setattr(core.http, "post_multipart",
                        lambda url, fields, fp: seen.update(url=url, fields=fields, fp=fp) or {"id": 42, "status": "received"})
    out = core.upload_document(path="/tmp/nda.pdf", parser="docling", chunker="docling-hybrid")
    assert out["id"] == 42
    assert seen["url"].endswith("/documents")          # library upload, no corpus
    assert seen["fields"]["parser"] == "docling"
    assert seen["fp"] == "/tmp/nda.pdf"


def test_upload_document_path_with_corpus_resolves_and_uses_corpus_endpoint(monkeypatch):
    monkeypatch.setattr(core.http, "get_json", lambda url: [{"id": 5, "name": "contracts"}])
    seen = {}
    monkeypatch.setattr(core.http, "post_multipart",
                        lambda url, fields, fp: seen.update(url=url) or {"id": 42, "status": "received"})
    core.upload_document(path="/tmp/nda.pdf", corpus="contracts")
    assert "/corpora/5/documents" in seen["url"]


def test_upload_document_base64_uses_json_ingest(monkeypatch):
    seen = {}
    monkeypatch.setattr(core.http, "post_json",
                        lambda url, payload: seen.update(url=url, payload=payload) or {"id": 9, "status": "received"})
    core.upload_document(content_b64="QUJD", filename="a.txt", corpus="c", parser="docling")
    assert seen["url"].endswith("/documents/ingest")
    assert seen["payload"]["content_b64"] == "QUJD"
    assert seen["payload"]["filename"] == "a.txt" and seen["payload"]["corpus"] == "c"


def test_upload_document_requires_exactly_one_source():
    with pytest.raises(http.CliError):
        core.upload_document()                               # neither
    with pytest.raises(http.CliError):
        core.upload_document(path="/x", content_b64="QUJD")  # both


def test_build_pipeline_posts_recipe_then_config(monkeypatch):
    calls = []
    monkeypatch.setattr(core.http, "post_json",
                        lambda url, payload: calls.append((url, payload)) or {"id": 3, "status": "building"})
    core.build_pipeline(42, "semantic", chunker="semantic")
    assert "/documents/42/pipelines" in calls[0][0]
    assert calls[0][1]["name"] == "semantic" and calls[0][1]["chunker"] == "semantic"
    core.build_pipeline(42, "raw", config={"slots": {}})
    assert calls[1][1]["config"] == {"slots": {}}


def test_add_document_to_corpus_resolves_then_posts(monkeypatch):
    monkeypatch.setattr(core.http, "get_json", lambda url: [{"id": 5, "name": "contracts"}])
    seen = {}
    monkeypatch.setattr(core.http, "post_json",
                        lambda url, payload=None: seen.update(url=url) or {"id": 42})
    core.add_document_to_corpus("contracts", 42)
    assert "/corpora/5/documents/42" in seen["url"]


def test_document_status_merges_doc_and_pipelines(monkeypatch):
    def fake_get(url):
        if url.endswith("/pipelines"):
            return [{"id": 3, "name": "semantic", "status": "indexed"}]
        return {"id": 42, "status": "indexed", "error": None, "progress": {"phase": "done"}}
    monkeypatch.setattr(core.http, "get_json", fake_get)
    out = core.document_status(42)
    assert out["status"] == "indexed"
    assert out["pipelines"][0]["name"] == "semantic"


def test_wait_for_document_drives_to_indexed(monkeypatch):
    seq = [{"status": "received", "pipelines": []},
           {"status": "indexing", "pipelines": []},
           {"status": "indexed", "pipelines": []}]
    monkeypatch.setattr(core, "document_status", lambda _id: seq.pop(0))
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    events = []
    out = core.wait_for_document(42, on_event=events.append, interval=0)
    assert out["status"] == "indexed"
    assert [e["status"] for e in events] == ["received", "indexing", "indexed"]


def test_wait_for_document_returns_on_failed(monkeypatch):
    monkeypatch.setattr(core, "document_status",
                        lambda _id: {"status": "failed", "error": "boom", "pipelines": []})
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    out = core.wait_for_document(42, interval=0)
    assert out["status"] == "failed" and out["error"] == "boom"


def test_wait_for_document_times_out(monkeypatch):
    monkeypatch.setattr(core, "document_status", lambda _id: {"status": "indexing", "pipelines": []})
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    ticks = iter([0.0, 0.0, 100.0, 200.0])
    monkeypatch.setattr(core.time, "monotonic", lambda: next(ticks))
    with pytest.raises(http.CliError):
        core.wait_for_document(42, interval=0, timeout=1.0)


def test_wait_for_pipeline_watches_named_pipeline(monkeypatch):
    seq = [{"pipelines": [{"id": 3, "status": "building"}]},
           {"pipelines": [{"id": 3, "status": "indexed"}]}]
    monkeypatch.setattr(core, "document_status", lambda _id: seq.pop(0))
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)
    out = core.wait_for_pipeline(42, 3, interval=0)
    assert out["pipelines"][0]["status"] == "indexed"


# ---------------------------------------------------------------------------
# Task 4: POST /documents/ingest (server-side integration tests)
# ---------------------------------------------------------------------------
import base64 as _b64
from fastapi.testclient import TestClient


def _api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'w2.db'}")
    monkeypatch.setenv("FILESTORE_DIR", str(tmp_path / "fs"))
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CORPORA_DIR", str(tmp_path / "corpora"))
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "0")
    import procrastinate
    from madosho_server import api, tasks
    tasks.use_connector(procrastinate.testing.InMemoryConnector())
    return api


def test_ingest_base64_creates_document_and_enqueues(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    with TestClient(api.app) as client:
        b64 = _b64.b64encode(b"hello world pdf bytes").decode()
        r = client.post("/documents/ingest", json={"filename": "a.txt", "content_b64": b64})
        assert r.status_code == 202
        doc_id = r.json()["id"]
        # same content again -> deduped to the same document (find-or-create by hash)
        r2 = client.post("/documents/ingest", json={"filename": "a.txt", "content_b64": b64})
        assert r2.json()["id"] == doc_id


def test_ingest_rejects_bad_base64(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    with TestClient(api.app) as client:
        r = client.post("/documents/ingest", json={"filename": "a.txt", "content_b64": "!!notb64!!"})
        assert r.status_code == 422


def test_ingest_rejects_oversize(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    with TestClient(api.app) as client:
        big = _b64.b64encode(b"x" * (50 * 1024 * 1024 + 1)).decode()
        r = client.post("/documents/ingest", json={"filename": "big.bin", "content_b64": big})
        assert r.status_code == 413


def test_ingest_with_corpus_creates_membership(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    with TestClient(api.app) as client:
        client.post("/corpora", json={"name": "contracts"})
        b64 = _b64.b64encode(b"doc for corpus").decode()
        r = client.post("/documents/ingest",
                        json={"filename": "c.txt", "content_b64": b64, "corpus": "contracts"})
        assert r.status_code == 202
        doc_id = r.json()["id"]
        chips = client.get(f"/documents/{doc_id}").json()["corpora"]
        assert any(c["name"] == "contracts" for c in chips)


def test_ingest_requires_write_scope_when_auth_on(tmp_path, monkeypatch):
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    api = _api(tmp_path, monkeypatch)            # note: sets the flag AFTER _api clears it
    monkeypatch.setenv("MADOSHO_AUTH_ENABLED", "1")
    from madosho_server import auth, db
    with TestClient(api.app) as client:
        with db.SessionLocal() as s:
            read_key = auth.create_key(s, "r2", "read")
            write_key = auth.create_key(s, "w2", "write")
        b64 = _b64.b64encode(b"scoped").decode()
        body = {"filename": "s.txt", "content_b64": b64}
        assert client.post("/documents/ingest", json=body,
                           headers={"Authorization": f"Bearer {read_key}"}).status_code == 403
        assert client.post("/documents/ingest", json=body,
                           headers={"Authorization": f"Bearer {write_key}"}).status_code == 202


# ---------------------------------------------------------------------------
# Mimetype preservation regression tests (Task 4 fix)
# ---------------------------------------------------------------------------

def test_library_multipart_upload_preserves_pdf_mimetype(tmp_path, monkeypatch):
    """POST /documents (multipart library upload) must store the Content-Type
    supplied by the client, not fall back to application/octet-stream."""
    api = _api(tmp_path, monkeypatch)
    from madosho_server import db
    with TestClient(api.app) as client:
        files = {"file": ("report.pdf", b"%PDF-1.4 minimal", "application/pdf")}
        r = client.post("/documents", files=files)
        assert r.status_code == 202
        doc_id = r.json()["id"]
    with db.SessionLocal() as s:
        doc = s.get(db.Document, doc_id)
        assert doc.mimetype == "application/pdf"


def test_ingest_base64_guesses_pdf_mimetype_from_filename(tmp_path, monkeypatch):
    """POST /documents/ingest must guess mimetype from filename when none is
    supplied, so a *.pdf filename yields application/pdf, not octet-stream."""
    api = _api(tmp_path, monkeypatch)
    from madosho_server import db
    with TestClient(api.app) as client:
        b64 = _b64.b64encode(b"%PDF-1.4 minimal").decode()
        r = client.post("/documents/ingest",
                        json={"filename": "report.pdf", "content_b64": b64})
        assert r.status_code == 202
        doc_id = r.json()["id"]
    with db.SessionLocal() as s:
        doc = s.get(db.Document, doc_id)
        assert doc.mimetype == "application/pdf"


def test_manifest_scopes_and_tool_set():
    tools = {t["name"]: t for t in _manifest.build_manifest()["tools"]}
    assert list(tools) == [
        "search", "search-doc", "get-doc", "list-corpora", "list-documents",
        "list-pipelines", "create-corpus", "upload-document", "build-pipeline",
        "add-document-to-corpus", "document-status",
        "list-goals", "goal-runs", "export-goal-run", "run-goal",
    ]
    assert tools["search"]["scope"] == "read"
    for w in ("create-corpus", "upload-document", "build-pipeline", "add-document-to-corpus"):
        assert tools[w]["scope"] == "write"
    assert tools["document-status"]["scope"] == "read"
    up = tools["upload-document"]
    assert up["parameters"]["required"] == []
    assert {"path", "content_b64"} <= set(up["parameters"]["properties"])


# ---------------------------------------------------------------------------
# Task 7: example pack (HEADLESS.md stub + stdlib ingest proof)
# ---------------------------------------------------------------------------

_REPO = pathlib.Path(__file__).resolve().parents[2]


def test_headless_example_is_ascii_stdlib_and_compiles():
    src = (_REPO / "examples" / "headless" / "ingest.py").read_text()
    src.encode("ascii")
    tree = ast.parse(src)
    imported = {n.module.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.Import) for a in n.names}
    stdlib = {"argparse", "base64", "json", "os", "sys", "time", "urllib", "http"}
    assert imported <= stdlib, f"must be stdlib-only, found {imported - stdlib}"


def test_headless_doc_exists():
    assert (_REPO / "docs" / "HEADLESS.md").exists()


# ---------------------------------------------------------------------------
# Task 6: CLI write subcommands
# ---------------------------------------------------------------------------

def _run(argv, monkeypatch, **core_stubs):
    for name, fn in core_stubs.items():
        monkeypatch.setattr(core, name, fn)
    return cli_main.main(argv)


def test_cli_create_corpus(monkeypatch, capsys):
    rc = _run(["create-corpus", "contracts", "--json"], monkeypatch,
              create_corpus=lambda name: {"id": 7, "name": name})
    assert rc == 0 and '"id": 7' in capsys.readouterr().out


def test_cli_upload_blocks_until_indexed(monkeypatch, capsys):
    monkeypatch.setattr(core, "upload_document", lambda **k: {"id": 42, "status": "received"})
    monkeypatch.setattr(core, "wait_for_document",
                        lambda _id, **k: {"id": 42, "status": "indexed", "pipelines": []})
    rc = _run(["upload-document", "/tmp/nda.pdf", "--corpus", "contracts"], monkeypatch)
    assert rc == 0 and "indexed" in capsys.readouterr().out


def test_cli_upload_no_wait_returns_id(monkeypatch, capsys):
    called = {"waited": False}
    monkeypatch.setattr(core, "upload_document", lambda **k: {"id": 42, "status": "received"})
    monkeypatch.setattr(core, "wait_for_document",
                        lambda *a, **k: called.__setitem__("waited", True))
    rc = _run(["upload-document", "/tmp/nda.pdf", "--no-wait", "--json"], monkeypatch)
    assert rc == 0 and called["waited"] is False and '"id": 42' in capsys.readouterr().out


def test_cli_build_pipeline_failed_returns_nonzero(monkeypatch):
    monkeypatch.setattr(core, "build_pipeline", lambda *a, **k: {"id": 3, "status": "building"})
    monkeypatch.setattr(core, "wait_for_pipeline",
                        lambda *a, **k: {"pipelines": [{"id": 3, "status": "failed", "error": "x"}]})
    rc = _run(["build-pipeline", "42", "semantic", "--chunker", "semantic"], monkeypatch)
    assert rc != 0


def test_cli_upload_failed_returns_nonzero(monkeypatch):
    monkeypatch.setattr(core, "upload_document", lambda **k: {"id": 42, "status": "received"})
    monkeypatch.setattr(core, "wait_for_document",
                        lambda _id, **k: {"id": 42, "status": "failed", "error": "boom", "pipelines": []})
    rc = _run(["upload-document", "/tmp/nda.pdf"], monkeypatch)
    assert rc != 0


# ---------------------------------------------------------------------------
# Cross-transport pipeline-name parity (base64 vs multipart must agree)
# ---------------------------------------------------------------------------

def test_base64_ingest_uses_sanitized_default_pipeline_name(tmp_path, monkeypatch):
    """POST /documents/ingest (base64) must derive the default pipeline name via
    default_pipeline_name(), not raw-filename. `report.pdf` -> `report_docling`,
    matching what POST /documents (multipart) produces."""
    api = _api(tmp_path, monkeypatch)
    from madosho_server import db
    from madosho_server.pipelines import default_pipeline_name
    with TestClient(api.app) as client:
        b64 = _b64.b64encode(b"%PDF-1.4 cross-transport-test").decode()
        r = client.post("/documents/ingest",
                        json={"filename": "report.pdf", "content_b64": b64})
        assert r.status_code == 202
        doc_id = r.json()["id"]
    expected = default_pipeline_name("report.pdf")   # "report_docling"
    with db.SessionLocal() as s:
        from sqlalchemy import select as _select
        pipelines = s.scalars(
            _select(db.Pipeline).where(db.Pipeline.document_id == doc_id)
        ).all()
    assert len(pipelines) == 1
    got = pipelines[0].name
    assert got == expected, (
        f"base64 ingest produced pipeline name {got!r}; expected {expected!r}. "
        "Both transports must use default_pipeline_name(), not the raw filename."
    )
    assert got != "report.pdf", "pipeline name must not be the raw filename"
