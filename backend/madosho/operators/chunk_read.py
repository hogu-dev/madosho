from pydantic import BaseModel

from madosho.core.protocols import OperatorDeps
from madosho.core.types import QueryContext
from madosho.operators._base import OperatorBase, operator_meta


class ChunkRead(OperatorBase):
    """Expand each final hit with neighboring chunks (window) from the store.
    Mostly an agent-facing tool later; in a pipeline it widens citations' context."""

    META = operator_meta("chunk_read")
    name = "chunk_read"

    class Options(BaseModel):
        window: int = 1

    params_schema = Options

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        for i, h in enumerate(ctx.hits):
            neighbors = deps.store.read([h.chunk_id], window=self.options.window)
            if neighbors:
                merged = h.chunk.model_copy(
                    update={"text": "\n".join(c.text for c in neighbors)})
                ctx.hits[i] = h.model_copy(update={"chunk": merged})
        return len(ctx.hits)
