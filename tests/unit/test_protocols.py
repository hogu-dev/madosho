import logging
from pathlib import Path

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext


META = ComponentMeta(name="thing", kind=ComponentKind.STORE, version="0", license="MIT",
                     org="o", org_country="US", origin_tier=OriginTier.US_SRC,
                     hardware=Hardware.CPU)


class FancyExtension:
    def snapshot(self): ...


class Thing(ComponentBase, FancyExtension):
    META = META


def test_extension_returns_self_when_implemented():
    t = Thing()
    assert t.extension(FancyExtension) is t


def test_extension_returns_none_when_not_implemented():
    class Other: ...
    assert Thing().extension(Other) is None


def test_meta_property_reads_class_attr():
    assert Thing().meta.name == "thing"


def test_native_defaults_to_none():
    assert Thing().native is None


def test_runtime_context_construction(tmp_path: Path):
    rt = RuntimeContext(corpus="c", data_dir=tmp_path, cache_dir=tmp_path / "cache",
                        logger=logging.getLogger("madosho.test"))
    assert rt.device == "cpu"


def test_multivector_search_is_a_runtime_checkable_extension():
    from madosho.core.protocols import ComponentBase, MultiVectorSearch

    class WithMv(ComponentBase):
        def multivector_search(self, name, vectors, k, filters=None):
            return []

    class WithoutMv(ComponentBase):
        pass

    assert isinstance(WithMv(), MultiVectorSearch)
    assert WithMv().extension(MultiVectorSearch) is not None
    assert WithoutMv().extension(MultiVectorSearch) is None
