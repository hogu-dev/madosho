from madosho_server.components import list_components


def test_list_components_groups_by_kind():
    out = list_components()
    assert "chunker" in out and "embedder" in out and "reranker" in out
    # each entry carries enough metadata to render a menu
    some = next(iter(out["chunker"]))
    assert set(some) >= {"name", "license", "org"}


def test_list_components_includes_parser():
    out = list_components()
    assert "parser" in out
    assert any(row["name"] == "docling" for row in out["parser"])


def test_list_components_exposes_slot_requirements():
    out = list_components()
    hybrid = next(r for r in out["chunker"] if r["name"] == "docling-hybrid")
    # serialized as {slot: [allowed names]} so the web form can enforce it live
    assert hybrid["requires"] == {"parser": ["docling", "router"]}
    # unconstrained components carry an empty map, not a missing key
    recursive = next(r for r in out["chunker"] if r["name"] == "recursive-text")
    assert recursive["requires"] == {}
