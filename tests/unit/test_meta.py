import pytest
from pydantic import ValidationError

from madosho.core.meta import (
    ComponentKind, ComponentMeta, Hardware, OriginTier, StoreCapabilities,
)


def test_component_meta_minimal():
    m = ComponentMeta(name="lancedb", kind=ComponentKind.STORE, version="0.1.0",
                      license="Apache-2.0", org="LanceDB", org_country="US",
                      origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU)
    assert m.base_lineage == [] and m.install_extra is None


def test_component_meta_rejects_bad_kind():
    with pytest.raises(ValidationError):
        ComponentMeta(name="x", kind="blender", version="1", license="MIT", org="o",
                      org_country="US", origin_tier=OriginTier.US_SRC,
                      hardware=Hardware.CPU)


def test_store_capabilities_default_off():
    caps = StoreCapabilities()
    assert not caps.native_bm25 and not caps.supports_multivector and not caps.supports_filters


def test_component_meta_is_frozen():
    m = ComponentMeta(name="x", kind=ComponentKind.STORE, version="1", license="MIT",
                      org="o", org_country="US", origin_tier=OriginTier.US_SRC,
                      hardware=Hardware.CPU)
    with pytest.raises(ValidationError):
        m.name = "mutated"
