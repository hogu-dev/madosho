from pydantic import BaseModel

from madosho.core.protocols import OperatorDeps
from madosho.core.types import QueryContext
from madosho.operators._base import OperatorBase, operator_meta


class KeywordSearch(OperatorBase):
    META = operator_meta("keyword_search")
    name = "keyword_search"

    class Options(BaseModel):
        k: int = 50

    params_schema = Options

    def _run(self, ctx: QueryContext, deps: OperatorDeps) -> int:
        self.require_capability(deps, "native_bm25")
        hits = deps.store.keyword_search(ctx.query, self.options.k)
        ctx.pools.append(hits)
        return len(hits)
