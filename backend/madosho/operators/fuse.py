from typing import Literal

from pydantic import BaseModel

from madosho.core.protocols import OperatorDeps
from madosho.core.types import Hit, QueryContext
from madosho.operators._base import OperatorBase, operator_meta


class Fuse(OperatorBase):
    """Merge all candidate pools into ctx.hits via reciprocal-rank fusion."""

    META = operator_meta("fuse")
    name = "fuse"

    class Options(BaseModel):
        method: Literal["rrf"] = "rrf"
        rrf_k: int = 60

    params_schema = Options

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        scores: dict[str, float] = {}
        best: dict[str, Hit] = {}
        for pool in ctx.pools:
            for rank, h in enumerate(pool):
                scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (self.options.rrf_k + rank + 1)
                best.setdefault(h.chunk_id, h)
        ctx.hits = sorted(
            (best[cid].model_copy(update={"score": s, "source_index": "rrf"})
             for cid, s in scores.items()),
            key=lambda h: (-h.score, h.chunk_id))
        ctx.pools = []   # consumed
        return len(ctx.hits)
