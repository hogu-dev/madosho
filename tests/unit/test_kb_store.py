from pathlib import Path

import pytest

from madosho_server import kb_store


def test_create_kb_lays_out_llmkb_format(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 7, "My KB")
    assert root == Path(tmp_path) / "kb-7"
    assert (root / "kb.yaml").read_text().startswith("name: My KB")
    for sub in ("wiki/summaries", "wiki/concepts", "wiki/entities", "raw"):
        assert (root / sub).is_dir()
    assert (root / "wiki" / "index.md").exists()
    assert (root / "wiki" / "log.md").exists()


def test_create_kb_rejects_existing(tmp_path):
    kb_store.create_kb(str(tmp_path), 7, "My KB")
    with pytest.raises(kb_store.KbStoreError):
        kb_store.create_kb(str(tmp_path), 7, "My KB")


def test_add_page_writes_format_correct_page_and_reindexes(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    page = kb_store.add_page(root, type="concept", title="Reranking",
                             description="reorder hits", tags=["ir"],
                             sources=["doc:3"], body="Body text.")
    assert page["slug"] == "reranking"
    written = (root / "wiki" / "concepts" / "reranking.md").read_text()
    assert written.startswith("---\ntype: concept\ntitle: Reranking\n")
    assert "Body text." in written
    assert "[[Reranking]]" in (root / "wiki" / "index.md").read_text()


def test_add_page_rejects_bad_type_and_empty_title(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    with pytest.raises(kb_store.KbStoreError):
        kb_store.add_page(root, type="bogus", title="X", description="d")
    with pytest.raises(kb_store.KbStoreError):
        kb_store.add_page(root, type="concept", title="   ", description="d")


def test_add_page_refuses_duplicate_title(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.add_page(root, type="concept", title="Reranking", description="d")
    with pytest.raises(kb_store.KbStoreError):
        kb_store.add_page(root, type="concept", title="Reranking", description="d2")


def test_slug_guard_contains_path_escape(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    page = kb_store.add_page(root, type="concept",
                             title="../../etc/passwd", description="d")
    written = root / "wiki" / "concepts" / (page["slug"] + ".md")
    assert written.resolve().parent == (root / "wiki" / "concepts").resolve()
    assert ".." not in page["slug"]  # traversal neutralized, not escaped


def test_get_and_edit_page_round_trip(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.add_page(root, type="entity", title="FAISS", description="lib",
                      body="orig")
    got = kb_store.get_page(root, "faiss")
    assert got["title"] == "FAISS" and got["body"] == "orig"
    edited = kb_store.edit_page(root, "faiss", description="vector lib",
                                body="updated")
    assert edited["description"] == "vector lib" and edited["body"] == "updated"
    assert kb_store.get_page(root, "faiss")["body"] == "updated"


def test_edit_missing_page_raises(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    with pytest.raises(kb_store.KbStoreError):
        kb_store.edit_page(root, "nope", body="x")


def test_find_by_slug_blocks_traversal(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    sentinel = tmp_path / "secret.md"
    sentinel.write_text("TOP SECRET", encoding="utf-8")

    traversal_slugs = [
        "../../secret",
        "../secret",
        "../../../../etc/passwd",
        "/etc/passwd",
        "..",
        "wiki/../../secret",
    ]
    for slug in traversal_slugs:
        assert kb_store.get_page(root, slug) is None, slug
        with pytest.raises(kb_store.KbStoreError):
            kb_store.edit_page(root, slug, body="pwned")

    # the sentinel file must be untouched by any of the attempts above
    assert sentinel.read_text(encoding="utf-8") == "TOP SECRET"


def test_list_and_search_pages(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.add_page(root, type="concept", title="Reranking",
                      description="reorder hits", body="cross encoder")
    kb_store.add_page(root, type="summary", title="RAG Overview",
                      description="intro", body="retrieval augmented")
    listed = {p["slug"] for p in kb_store.list_pages(root)}
    assert listed == {"reranking", "rag-overview"}
    hits = kb_store.search_pages(root, "cross encoder")
    assert [h["slug"] for h in hits] == ["reranking"]


def test_import_from_folder_copies_pages(tmp_path):
    src = kb_store.create_kb(str(tmp_path / "src"), 99, "Src")
    kb_store.add_page(src, type="concept", title="Chunking", description="split")
    dest = kb_store.import_from_folder(str(tmp_path / "dst"), 5, "Dest", src)
    assert dest == Path(tmp_path / "dst") / "kb-5"
    assert (dest / "wiki" / "concepts" / "chunking.md").exists()
    assert "[[Chunking]]" in (dest / "wiki" / "index.md").read_text()


def test_move_page_retype_within_kb_relocates_and_preserves_fields(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.add_page(root, type="concept", title="Reranking", description="reorder",
                      tags=["ir"], sources=["doc:3"], body="Body.")
    moved = kb_store.move_page(root, "reranking", dest_root=root, new_type="summary")
    assert moved["type"] == "summary" and moved["slug"] == "reranking"
    # fields other than type survive
    assert moved["description"] == "reorder" and moved["tags"] == ["ir"]
    assert moved["sources"] == ["doc:3"] and moved["body"] == "Body."
    # file physically relocated between subdirs
    assert not (root / "wiki" / "concepts" / "reranking.md").exists()
    assert (root / "wiki" / "summaries" / "reranking.md").exists()
    # index reflects the new home
    assert "[[Reranking]]" in kb_store.read_index(root)


def test_move_page_between_kbs(tmp_path):
    src = kb_store.create_kb(str(tmp_path), 1, "Src")
    dest = kb_store.create_kb(str(tmp_path), 2, "Dest")
    kb_store.add_page(src, type="concept", title="Reranking", description="d",
                      tags=["ir"], sources=[], body="Body.")
    moved = kb_store.move_page(src, "reranking", dest_root=dest, new_type="concept")
    assert moved["title"] == "Reranking" and moved["type"] == "concept"
    assert kb_store.get_page(src, "reranking") is None
    assert kb_store.get_page(dest, "reranking") is not None
    assert "[[Reranking]]" not in kb_store.read_index(src)
    assert "[[Reranking]]" in kb_store.read_index(dest)


def test_move_page_rejects_destination_collision(tmp_path):
    src = kb_store.create_kb(str(tmp_path), 1, "Src")
    dest = kb_store.create_kb(str(tmp_path), 2, "Dest")
    kb_store.add_page(src, type="concept", title="Reranking", description="d")
    kb_store.add_page(dest, type="concept", title="Reranking", description="other")
    with pytest.raises(kb_store.KbStoreError, match="already exists"):
        kb_store.move_page(src, "reranking", dest_root=dest, new_type="concept")
    # source page untouched after the failed move
    assert kb_store.get_page(src, "reranking") is not None


def test_move_page_rejects_missing_slug_and_noop(tmp_path):
    root = kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.add_page(root, type="concept", title="Reranking", description="d")
    with pytest.raises(kb_store.KbStoreError, match="no page"):
        kb_store.move_page(root, "ghost", dest_root=root, new_type="summary")
    with pytest.raises(kb_store.KbStoreError, match="already"):
        kb_store.move_page(root, "reranking", dest_root=root, new_type="concept")


def test_delete_kb_removes_folder(tmp_path):
    kb_store.create_kb(str(tmp_path), 1, "KB")
    kb_store.delete_kb(str(tmp_path), 1)
    assert not (Path(tmp_path) / "kb-1").exists()


def test_kb_model_and_unique_constraint():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    from madosho_server import db

    eng = create_engine("sqlite://")
    db.Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(db.Corpus(name="c1", config={}))
        s.commit()
        s.add(db.Kb(corpus_id=1, name="Notes", slug="notes"))
        s.commit()
        s.add(db.Kb(corpus_id=1, name="Notes", slug="notes"))
        import pytest
        with pytest.raises(IntegrityError):
            s.commit()


def test_settings_reads_kb_dir(monkeypatch):
    from madosho_server.settings import Settings
    monkeypatch.setenv("KB_DIR", "/tmp/kbs-test")
    assert Settings.from_env().kb_dir == "/tmp/kbs-test"
