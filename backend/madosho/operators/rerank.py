from pydantic import BaseModel

from madosho.core.protocols import OperatorDeps
from madosho.core.types import QueryContext
from madosho.operators._base import OperatorBase, operator_meta


class Rerank(OperatorBase):
    META = operator_meta("rerank")
    name = "rerank"

    class Options(BaseModel):
        model: str
        top_k: int = 8

    params_schema = Options

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        reranker = deps.reranker_for(self.options.model)
        ctx.hits = reranker.rerank(ctx.query, ctx.hits, self.options.top_k)
        return len(ctx.hits)
