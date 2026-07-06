import logging

import pytest

from madosho.core.errors import MissingDependencyError, UnknownComponentError
from madosho.core.hooks import Resolution, ResolutionAction, ResolutionContext
from madosho.core.meta import ComponentKind
from madosho.core.registry import ComponentSpec, Registry
from madosho.core.protocols import RuntimeContext
from madosho.testing.fakes import FakeStore

CTX = ResolutionContext(corpus="c")


def runtime(tmp_path) -> RuntimeContext:
    return RuntimeContext(corpus="c", data_dir=tmp_path, cache_dir=tmp_path,
                          logger=logging.getLogger("madosho.test"))


def fresh_registry() -> Registry:
    return Registry(specs=[
        ComponentSpec(kind=ComponentKind.STORE, name="fake-store",
                      target="madosho.testing.fakes:FakeStore", install_extra=None),
        ComponentSpec(kind=ComponentKind.STORE, name="ghost",
                      target="madosho.adapters.nonexistent:Ghost", install_extra="ghost"),
    ])


def test_resolve_instantiates_with_options_and_runtime(tmp_path):
    store = fresh_registry().resolve(ComponentKind.STORE, "fake-store", {}, runtime(tmp_path), CTX)
    assert isinstance(store, FakeStore) and store.runtime.corpus == "c"


def test_unknown_name_suggests_close_match(tmp_path):
    with pytest.raises(UnknownComponentError, match="fake-store"):
        fresh_registry().resolve(ComponentKind.STORE, "fake-stor", {}, runtime(tmp_path), CTX)


def test_missing_dependency_names_the_pip_fix(tmp_path):
    with pytest.raises(MissingDependencyError, match=r'pip install "madosho\[ghost\]"'):
        fresh_registry().resolve(ComponentKind.STORE, "ghost", {}, runtime(tmp_path), CTX)


def test_invalid_options_fail_fast(tmp_path):
    from madosho.core.errors import ConfigError
    with pytest.raises(ConfigError, match="fake-store"):
        fresh_registry().resolve(ComponentKind.STORE, "fake-store",
                                 {"no_such_option": 1}, runtime(tmp_path), CTX)


def test_entry_point_discovery(monkeypatch):
    class EP:
        name = "store.toy"
        value = "madosho.testing.fakes:FakeStore"

    monkeypatch.setattr("madosho.core.registry.entry_points", lambda group: [EP()])
    reg = fresh_registry()
    reg.discover_entry_points()
    assert "toy" in reg.names(ComponentKind.STORE)


def test_hooks_run_at_resolution(tmp_path):
    from madosho.core.errors import ComponentDeniedError

    def deny(meta, ctx):
        return Resolution(action=ResolutionAction.DENY, message="nope")

    reg = fresh_registry()
    reg.hooks = [deny]
    with pytest.raises(ComponentDeniedError):
        reg.resolve(ComponentKind.STORE, "fake-store", {}, runtime(tmp_path), CTX)


def test_broken_target_is_a_config_error(tmp_path):
    from madosho.core.errors import ConfigError
    reg = Registry(specs=[ComponentSpec(kind=ComponentKind.STORE, name="bad",
                                        target="madosho.testing.fakes:NoSuchClass",
                                        install_extra=None)])
    with pytest.raises(ConfigError, match="NoSuchClass"):
        reg.resolve(ComponentKind.STORE, "bad", {}, runtime(tmp_path), CTX)


def test_component_without_meta_or_options_is_a_config_error(tmp_path):
    from madosho.core.errors import ConfigError
    reg = Registry(specs=[ComponentSpec(kind=ComponentKind.STORE, name="bare",
                                        target="madosho.core.registry:Registry",
                                        install_extra=None)])
    with pytest.raises(ConfigError, match="malformed"):
        reg.resolve(ComponentKind.STORE, "bare", {}, runtime(tmp_path), CTX)


def test_aliased_options_accept_the_alias(tmp_path):
    from pydantic import BaseModel, Field

    from madosho.core.protocols import ComponentBase
    from madosho.testing.fakes import _meta

    class Aliased(ComponentBase):
        META = _meta("aliased", ComponentKind.STORE)

        class Options(BaseModel):
            top_k: int = Field(default=5, alias="topK")

        def __init__(self, options, runtime):
            self.options = options

    import madosho.testing.fakes as fakes
    fakes.Aliased = Aliased
    try:
        reg = Registry(specs=[ComponentSpec(kind=ComponentKind.STORE, name="aliased",
                                            target="madosho.testing.fakes:Aliased",
                                            install_extra=None)])
        comp = reg.resolve(ComponentKind.STORE, "aliased", {"topK": 9},
                           runtime(tmp_path), CTX)
        assert comp.options.top_k == 9
    finally:
        del fakes.Aliased


def test_empty_entry_point_name_is_skipped(monkeypatch):
    class EP:
        name = "store."
        value = "madosho.testing.fakes:FakeStore"

    monkeypatch.setattr("madosho.core.registry.entry_points", lambda group: [EP()])
    reg = fresh_registry()
    reg.discover_entry_points()
    assert "" not in reg.names(ComponentKind.STORE)


def test_builtin_wins_over_plugin_collision(monkeypatch):
    class EP:
        name = "store.fake-store"
        value = "madosho.core.registry:Registry"   # would be malformed if it won

    monkeypatch.setattr("madosho.core.registry.entry_points", lambda group: [EP()])
    reg = fresh_registry()
    reg.discover_entry_points()
    assert reg.spec(ComponentKind.STORE, "fake-store").target == "madosho.testing.fakes:FakeStore"


# --- slot dependencies (hard data-flow constraints, NOT curation) ----------
from madosho.core.registry import requirement_errors  # noqa: E402


def test_docling_hybrid_declares_it_needs_the_docling_parser():
    # The docling-hybrid chunker reads the docling parser's native object, so it
    # only runs on parsers that produce one (docling, or router's default lane).
    spec = Registry().spec(ComponentKind.CHUNKER, "docling-hybrid")
    assert ("parser", ("docling", "router")) in spec.requires


def test_requirement_errors_empty_for_compatible_recipe():
    errs = requirement_errors({"parser": "docling", "chunker": "docling-hybrid",
                               "embedder": "granite-embedding-english-r2"})
    assert errs == {}
    # router's default lane produces a docling document too -> also valid
    assert requirement_errors({"parser": "router", "chunker": "docling-hybrid"}) == {}


def test_requirement_errors_flags_the_requiring_slot():
    # pymupdf parser + docling-hybrid chunker -> the CHUNKER slot is flagged
    # (it owns the unmet requirement), and the message names the needed parser.
    errs = requirement_errors({"parser": "pymupdf", "chunker": "docling-hybrid"})
    assert set(errs) == {"chunker"}
    assert "docling" in errs["chunker"]


def test_requirement_errors_unconstrained_components_never_flagged():
    errs = requirement_errors({"parser": "pymupdf", "chunker": "recursive-text"})
    assert errs == {}
