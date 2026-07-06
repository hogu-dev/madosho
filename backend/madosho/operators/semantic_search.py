from pydantic import BaseModel

from madosho.core.protocols import OperatorDeps
from madosho.core.types import QueryContext
from madosho.operators._base import OperatorBase, operator_meta


class SemanticSearch(OperatorBase):
    META = operator_meta("semantic_search")
    name = "semantic_search"

    class Options(BaseModel):
        k: int = 50

    params_schema = Options

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        vector = ctx.query_vector(deps.embedder)
        hits = deps.store.semantic_search(vector, self.options.k)
        ctx.pools.append(hits)
        return len(hits)
