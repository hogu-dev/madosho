from madosho_server.components import list_components


def test_components_include_options_schema_for_chunkers():
    comps = list_components()
    chunkers = {c["name"]: c for c in comps["chunker"]}
    rec = chunkers["recursive-text"]
    assert "options_schema" in rec
    props = rec["options_schema"]["properties"]
    assert "max_chars" in props and "overlap" in props
    assert props["max_chars"]["default"] == 1200

    sem = chunkers["semantic"]["options_schema"]["properties"]
    assert "breakpoint_percentile" in sem and "max_chars" in sem


def test_load_failure_row_has_null_options_schema(monkeypatch):
    # force load_class to raise for one component and confirm the fallback row
    # still carries options_schema=None rather than omitting the key
    import madosho_server.components as mod

    real = mod.Registry.load_class

    def boom(self, kind, name):
        if name == "recursive-text":
            raise RuntimeError("simulated import failure")
        return real(self, kind, name)

    monkeypatch.setattr(mod.Registry, "load_class", boom)
    comps = list_components()
    rec = {c["name"]: c for c in comps["chunker"]}["recursive-text"]
    assert rec["options_schema"] is None
