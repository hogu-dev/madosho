from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator,
)

from madosho.core.errors import ConfigError


class ComponentRef(BaseModel):
    """A component mention in config: bare name, or {name: {options}}."""

    name: str
    options: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def coerce(cls, value: Any) -> "ComponentRef":
        if isinstance(value, ComponentRef):
            return value
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, dict):
            if len(value) != 1:
                raise ValueError(
                    f"component reference must have exactly one key, got {sorted(value)}")
            name, options = next(iter(value.items()))
            return cls(name=name, options=options or {})
        raise ValueError(f"cannot interpret component reference: {value!r}")


class IngestSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parser: ComponentRef
    chunker: ComponentRef
    embedder: ComponentRef
    store: ComponentRef
    indexes: list[str] = Field(default_factory=lambda: ["bm25", "dense"])

    @field_validator("parser", "chunker", "embedder", "store", mode="before")
    @classmethod
    def _coerce(cls, v):
        return ComponentRef.coerce(v)

    @model_validator(mode="after")
    def _check_slot_requirements(self):
        # Hard data-flow compatibility (e.g. the docling-hybrid chunker needs the
        # docling parser's native object). Fail here, at config-validation time,
        # rather than as a cryptic raise mid-build. Imported lazily to avoid a
        # config<->registry import cycle. NOT a curation gate.
        from madosho.core.registry import requirement_errors

        errors = requirement_errors({
            "parser": self.parser.name, "chunker": self.chunker.name,
            "embedder": self.embedder.name, "store": self.store.name})
        if errors:
            detail = "; ".join(f"{slot} '{getattr(self, slot).name}' {msg}"
                               for slot, msg in errors.items())
            raise ValueError(f"incompatible pipeline: {detail}")
        return self


class MadoshoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source: Path | None = None
    ingest: IngestSection
    query: list[ComponentRef]
    config_path: Path | None = Field(default=None, exclude=True)

    @field_validator("source")
    @classmethod
    def _expand_source(cls, v: Path | None) -> Path | None:
        return v.expanduser() if v is not None else None

    @field_validator("query", mode="before")
    @classmethod
    def _coerce_steps(cls, v):
        if not isinstance(v, list):
            raise ValueError("query must be a list of operator steps")
        return [ComponentRef.coerce(step) for step in v]


def load_config(path: str | Path) -> MadoshoConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    try:
        cfg = MadoshoConfig(**raw)
    except (ValidationError, ValueError) as e:
        raise ConfigError(f"invalid config {path}: {e}") from e
    cfg.config_path = path
    if cfg.source is not None and not cfg.source.is_absolute():
        # relative source is anchored to madosho.yaml, not the process cwd
        # (mirrors the .madosho/ state anchoring in open_corpus)
        cfg.source = path.parent / cfg.source
    return cfg
