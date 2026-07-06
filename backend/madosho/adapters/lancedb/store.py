from __future__ import annotations

from pydantic import BaseModel

from madosho.core.errors import MadoshoError
from madosho.core.meta import (
    ComponentKind, ComponentMeta, Hardware, OriginTier, StoreCapabilities,
)
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import (
    Chunk, EmbeddedChunk, Filters, Hit, IndexSpec, Vector,
)

TABLE = "chunks"
FILTER_COLUMNS = {"id", "doc_id", "text", "context_prefix", "position", "page", "source"}


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _filters_to_sql(filters: Filters | None) -> str | None:
    if filters is None:
        return None
    bad = (set(filters.equals) | set(filters.any_of) | set(filters.ranges)) - FILTER_COLUMNS
    if bad:
        raise MadoshoError(f"unknown filter column(s): {sorted(bad)}. "
                         f"Filterable: {sorted(FILTER_COLUMNS)}")
    clauses = []
    fmt = lambda v: _quote(v) if isinstance(v, str) else str(v)
    for k, v in filters.equals.items():
        clauses.append(f"{k} = {fmt(v)}")
    for k, allowed in filters.any_of.items():
        if not allowed:
            clauses.append("1=0")   # empty allow-set matches nothing
            continue
        clauses.append(f"{k} IN ({', '.join(fmt(v) for v in allowed)})")
    for k, (lo, hi) in filters.ranges.items():
        clauses.append(f"{k} >= {fmt(lo)} AND {k} <= {fmt(hi)}")
    return " AND ".join(clauses) if clauses else None


class LanceDBStore(ComponentBase):
    """LanceDB-backed chunk store.

    FTS freshness is per-instance: a long-lived instance does not see another live instance's
    writes until its own next mutation. Single-process usage (one Corpus) is unaffected.
    """

    META = ComponentMeta(
        name="lancedb", kind=ComponentKind.STORE, version="0.1.0",
        license="Apache-2.0", org="LanceDB", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra="lancedb")

    capabilities = StoreCapabilities(native_bm25=True, supports_filters=True)

    class Options(BaseModel):
        uri: str | None = None   # default: <runtime.data_dir>/lancedb

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        import lancedb  # deferred: optional dependency

        self.options = options or self.Options()
        self.runtime = runtime
        uri = self.options.uri or (str(runtime.data_dir / "lancedb") if runtime else None)
        if uri is None:
            raise MadoshoError("lancedb store needs either options.uri or a RuntimeContext")
        self._db = lancedb.connect(uri)
        self._table = None
        self._dims: int | None = None
        self._fts_dirty = True

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    @property
    def native(self):
        return self._db

    # -- schema --------------------------------------------------------------

    def ensure_schema(self, spec: IndexSpec) -> None:
        import pyarrow as pa

        self._dims = spec.vectors["dense"]
        schema = pa.schema([
            pa.field("id", pa.utf8()),
            pa.field("doc_id", pa.utf8()),
            pa.field("text", pa.utf8()),
            pa.field("context_prefix", pa.utf8()),
            pa.field("position", pa.int32()),
            pa.field("page", pa.int32(), nullable=True),
            pa.field("source", pa.utf8()),
            pa.field("vector", pa.list_(pa.float32(), self._dims)),
        ])
        self._table = self._db.create_table(TABLE, schema=schema, exist_ok=True)

    def _require_table(self):
        if self._table is None:
            raise MadoshoError("ensure_schema() must run before using the store")
        return self._table

    # -- rows <-> chunks -------------------------------------------------------

    @staticmethod
    def _row(ec: EmbeddedChunk) -> dict:
        c = ec.chunk
        return {"id": c.id, "doc_id": c.doc_id, "text": c.text,
                "context_prefix": c.context_prefix, "position": c.position,
                "page": c.page, "source": c.metadata.get("source", ""),
                "vector": ec.vectors["dense"]}

    @staticmethod
    def _chunk(row: dict) -> Chunk:
        return Chunk(id=row["id"], doc_id=row["doc_id"], text=row["text"],
                     context_prefix=row["context_prefix"], position=row["position"],
                     page=row["page"],
                     metadata={"source": row["source"]} if row["source"] else {})

    # -- store protocol --------------------------------------------------------

    def upsert(self, chunks: list[EmbeddedChunk]) -> None:
        table = self._require_table()
        (table.merge_insert(["id"])
              .when_matched_update_all()
              .when_not_matched_insert_all()
              .execute([self._row(ec) for ec in chunks]))
        self._fts_dirty = True

    def delete(self, doc_ids: list[str]) -> None:
        if doc_ids:
            self._require_table().delete(
                f"doc_id IN ({', '.join(_quote(d) for d in doc_ids)})")
            self._fts_dirty = True

    def _ensure_fts(self) -> None:
        if self._fts_dirty:
            # native (tantivy-free) BM25 index; replace=True refreshes after upserts.
            self._require_table().create_fts_index("text", use_tantivy=False, replace=True)
            self._fts_dirty = False

    def keyword_search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        self._ensure_fts()
        q = self._require_table().search(query, query_type="fts").limit(k)
        if (where := _filters_to_sql(filters)):
            q = q.where(where)
        return [Hit(chunk_id=r["id"], score=float(r["_score"]), source_index="bm25",
                    chunk=self._chunk(r)) for r in q.to_list()]

    def semantic_search(self, vector: Vector, k: int, filters: Filters | None = None) -> list[Hit]:
        # Embedders L2-normalize, so default L2 distance ranks identically to cosine.
        # score = 1/(1+L2): squashes distance into (0,1], rank-preserving, not calibrated.
        q = self._require_table().search(vector).limit(k)
        if (where := _filters_to_sql(filters)):
            q = q.where(where)
        return [Hit(chunk_id=r["id"], score=1.0 / (1.0 + float(r["_distance"])),
                    source_index="dense", chunk=self._chunk(r)) for r in q.to_list()]

    def read(self, chunk_ids: list[str], window: int = 0) -> list[Chunk]:
        table = self._require_table()
        if not chunk_ids:
            return []
        anchor_rows = (table.search()
                       .where(f"id IN ({', '.join(_quote(c) for c in chunk_ids)})")
                       .to_list())
        out: dict[str, Chunk] = {}
        for row in anchor_rows:
            lo, hi = row["position"] - window, row["position"] + window
            for r in (table.search()
                      .where(f"doc_id = {_quote(row['doc_id'])} AND "
                             f"position >= {lo} AND position <= {hi}")
                      .to_list()):
                out[r["id"]] = self._chunk(r)
        return sorted(out.values(), key=lambda c: (c.doc_id, c.position))
