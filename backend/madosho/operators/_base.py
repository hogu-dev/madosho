from __future__ import annotations

import time

from pydantic import BaseModel

from madosho.core.errors import CapabilityError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, OperatorDeps, RuntimeContext
from madosho.core.types import QueryContext


def operator_meta(name: str) -> ComponentMeta:
    return ComponentMeta(name=name, kind=ComponentKind.OPERATOR, version="0.1.0",
                         license="Apache-2.0", org="madosho", org_country="US",
                         origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU)


class OperatorBase(ComponentBase):
    name: str

    class Options(BaseModel):
        pass

    # params_schema doubles as the agent tool schema later (spec §5.1).
    # Every subclass re-points this at its own Options: `params_schema = Options`.
    params_schema: type[BaseModel] = Options

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # params_schema always tracks the subclass's own Options; an author who
        # forgets the manual re-point must not silently ship an empty schema.
        cls.params_schema = cls.Options

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def require_capability(self, deps: OperatorDeps, flag: str) -> None:
        if not getattr(deps.store.capabilities, flag):
            raise CapabilityError(
                f"operator '{self.name}' requires store capability '{flag}', "
                f"but store '{deps.store.meta.name}' does not provide it")

    def run(self, ctx: QueryContext, deps: OperatorDeps) -> QueryContext:
        started = time.monotonic()
        added = self._run(ctx, deps)
        ctx.record(self.name, self.options.model_dump(), added, started)
        return ctx

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        raise NotImplementedError
