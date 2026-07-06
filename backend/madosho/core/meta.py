from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ComponentKind(StrEnum):
    PARSER = "parser"
    CHUNKER = "chunker"
    EMBEDDER = "embedder"
    STORE = "store"
    RERANKER = "reranker"
    OPERATOR = "operator"


class OriginTier(StrEnum):
    # Factual source summary for procurement checks (docs/COMPLIANCE.md defines
    # the jurisdiction lists and maps these to actual rule texts). Labels are
    # informational only -- madosho never gates on them.
    US_SRC = "us_src"            # US org AND US base weights
    ALLIED_SRC = "allied_src"    # org and lineage within the US/allied set
    CN_OTH_SRC = "cn_oth_src"    # org or lineage outside that set (China is
                                 # the common case; org_country has the country)


class Hardware(StrEnum):
    CPU = "cpu"
    GPU_SMALL = "gpu_small"
    GPU_LARGE = "gpu_large"


class ComponentMeta(BaseModel):
    """Informational card on every component. Never consulted to allow/deny
    anything in core -- labels are facts to filter on, not gates."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: ComponentKind
    version: str
    license: str               # SPDX id, self-declared
    org: str
    org_country: str
    base_lineage: list[str] = Field(default_factory=list)
    origin_tier: OriginTier
    hardware: Hardware
    install_extra: str | None = None


class StoreCapabilities(BaseModel):
    native_bm25: bool = False
    supports_multivector: bool = False
    supports_filters: bool = False
