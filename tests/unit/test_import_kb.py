import base64
from madosho_cli import commands
from madosho_cli.main import main


def _make_kb(root):
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "kb.yaml").write_text("name: demo-kb\nformat: 1\n")
    (root / "wiki" / "index.md").write_text("# Index\n")
    (root / "wiki" / "concepts" / "alpha.md").write_text(
        "---\ntype: concept\ntitle: Alpha\ndescription: d\ntags: []\n"
        "timestamp: 2026-07-11\nsources: []\n---\n\nAlpha body.\n")
    return root


def test_import_kb_packs_and_uploads(tmp_path, monkeypatch):
    kb = _make_kb(tmp_path / "demo-kb")
    seen = {}

    def fake_upload(content_b64=None, filename=None, corpus=None, **kw):
        seen.update(content_b64=content_b64, filename=filename, corpus=corpus)
        return {"id": 5, "status": "received"}

    monkeypatch.setattr(commands.core, "upload_document", fake_upload)
    rc = main(["import-kb", str(kb), "--corpus", "kbtest", "--no-wait", "--json"])
    assert rc == 0
    assert seen["filename"] == "demo-kb.md" and seen["corpus"] == "kbtest"
    decoded = base64.b64decode(seen["content_b64"]).decode("utf-8")
    assert "Alpha body." in decoded and "demo-kb" in decoded


def test_import_kb_bad_dir(tmp_path):
    rc = main(["import-kb", str(tmp_path)])  # no kb.yaml
    assert rc == 1
