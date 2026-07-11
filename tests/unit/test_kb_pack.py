import pytest
from madosho_cli import kb_pack


def _make_kb(root):
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "summaries").mkdir(parents=True)
    (root / "kb.yaml").write_text("name: demo-kb\ndescription: d\nformat: 1\n")
    (root / "wiki" / "index.md").write_text("# Index\n\n## Concepts\n- [[Alpha]]\n")
    (root / "wiki" / "concepts" / "alpha.md").write_text(
        "---\ntype: concept\ntitle: Alpha\ndescription: d\ntags: [x]\n"
        "timestamp: 2026-07-11\nsources: []\n---\n\nAlpha body here.\n")
    return root


def test_pack_kb_returns_filename_and_content(tmp_path):
    kb = _make_kb(tmp_path / "demo-kb")
    filename, content = kb_pack.pack_kb(kb)
    assert filename == "demo-kb.md"
    assert "demo-kb" in content              # identity header
    assert "Alpha body here." in content     # page body
    assert "type: concept" in content        # frontmatter kept as signal
    assert "wiki/concepts/alpha.md" in content  # page provenance marker


def test_pack_kb_missing_yaml(tmp_path):
    (tmp_path / "wiki").mkdir()
    with pytest.raises(kb_pack.KbPackError):
        kb_pack.pack_kb(tmp_path)


def test_pack_kb_bad_format(tmp_path):
    (tmp_path / "kb.yaml").write_text("name: x\nformat: 2\n")
    with pytest.raises(kb_pack.KbPackError):
        kb_pack.pack_kb(tmp_path)
