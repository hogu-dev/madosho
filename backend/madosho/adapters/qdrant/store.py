from __future__ import annotations

import os
import re
import uuid

from pydantic import BaseModel

from madosho.adapters.qdrant.sparse import encode_document, encode_query
from madosho.core.errors import MadoshoError
from madosho.core.meta import (
    ComponentKind, ComponentMeta, Hardware, OriginTier, StoreCapabilities,
)
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import (
    Chunk, EmbeddedChunk, Filters, Hit, IndexSpec, Vector,
)

DENSE_INDEX = "dense"
SPARSE_INDEX = "bm25"
# text/context_prefix are filterable but deliberately not payload-indexed
# (rarely filtered; unindexed filters scan, they don't fail)
FILTER_COLUMNS = {"id", "doc_id", "text", "context_prefix", "position", "page", "source"}

# chunk ids are arbitrary strings; Qdrant point ids must be uint64 or UUID.
# uuid5 in a fixed namespace keeps the mapping deterministic, so re-upserting
# the same chunk id overwrites its point. The original id lives in the payload.
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "madosho/qdrant-store")

# returned by _to_filter when an empty any_of allow-set can match nothing
_IMPOSSIBLE = object()


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


def _to_filter(filters: Filters | None):
    from qdrant_client import models

    if filters is None:
        return None
    bad = (set(filters.equals) | set(filters.any_of) | set(filters.ranges)) - FILTER_COLUMNS
    if bad:
        raise MadoshoError(f"unknown filter column(s): {sorted(bad)}. "
                         f"Filterable: {sorted(FILTER_COLUMNS)}")
    must = []
    for k, v in filters.equals.items():
        if isinstance(v, float):
            # Qdrant match conditions take str/int/bool; floats go through range
            must.append(models.FieldCondition(key=k, range=models.Range(gte=v, lte=v)))
        else:
            must.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))
    for k, allowed in filters.any_of.items():
        if not allowed:
            return _IMPOSSIBLE      # empty allow-set matches nothing
        if any(isinstance(v, float) for v in allowed):
            raise MadoshoError(f"float values in any_of filters are not supported "
                             f"by the qdrant store (column '{k}')")
        must.append(models.FieldCondition(key=k, match=models.MatchAny(any=list(allowed))))
    for k, (lo, hi) in filters.ranges.items():
        must.append(models.FieldCondition(key=k, range=models.Range(gte=lo, lte=hi)))
    return models.Filter(must=must) if must else None


class QdrantStore(ComponentBase):
    """Qdrant-backed chunk store (server, local-path, or in-memory local mode).

    Keyword search runs on a server-side-IDF sparse index fed by a client-side
    BM25 term-frequency encoder over chunk.embed_text. Unlike the LanceDB
    store, the full chunk.metadata dict round-trips through the payload.
    """

    META = ComponentMeta(
        name="qdrant", kind=ComponentKind.STORE, version="0.1.0",
        license="Apache-2.0", org="Qdrant", org_country="DE",
        origin_tier=OriginTier.ALLIED_SRC, hardware=Hardware.CPU,
        install_extra="qdrant")

    capabilities = StoreCapabilities(native_bm25=True, supports_filters=True,
                                     supports_multivector=True)

    class Options(BaseModel):
        url: str | None = None        # Qdrant server, e.g. "http://localhost:6333"
        location: str | None = None   # ":memory:" in-process local mode (tests)
        path: str | None = None       # on-disk local mode directory (no server)
        # Server API key is read from this env var — never placed in madosho.yaml.
        api_key_env: str = "QDRANT_API_KEY"
        collection: str | None = None  # default: "madosho_<corpus>" from runtime

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        from qdrant_client import QdrantClient  # deferred: optional dependency

        self.options = options or self.Options()
        self.runtime = runtime
        modes = [m for m in (self.options.location, self.options.url, self.options.path) if m]
        if len(modes) > 1:
            raise MadoshoError("qdrant store: set at most one of location/url/path")
        name = self.options.collection or (
            re.sub(r"[^A-Za-z0-9_]", "_", f"madosho_{runtime.corpus}") if runtime else None)
        if name is None:
            raise MadoshoError("qdrant store needs options.collection or a RuntimeContext")
        self._collection = name
        if self.options.location:
            self._client = QdrantClient(location=self.options.location)
        elif self.options.path:
            self._client = QdrantClient(path=self.options.path)
        else:
            self._client = QdrantClient(
                url=self.options.url or "http://localhost:6333",
                api_key=os.environ.get(self.options.api_key_env) or None)
        self._spec: IndexSpec | None = None

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    @property
    def native(self):
        return self._client

    # -- schema ----------------------------------------------------------------

    def ensure_schema(self, spec: IndexSpec) -> None:
        from qdrant_client import models

        self._spec = spec
        if self._client.collection_exists(self._collection):
            self._validate_dims(spec)
            return
        vectors_config = {n: models.VectorParams(size=d, distance=models.Distance.COSINE)
                          for n, d in spec.vectors.items()}
        vectors_config |= {
            n: models.VectorParams(
                size=d, distance=models.Distance.COSINE,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM))
            for n, d in spec.multivectors.items()}
        sparse = ({SPARSE_INDEX: models.SparseVectorParams(modifier=models.Modifier.IDF)}
                  if SPARSE_INDEX in spec.indexes else None)
        self._client.create_collection(self._collection, vectors_config=vectors_config,
                                       sparse_vectors_config=sparse)
        for field, schema in (("id", models.PayloadSchemaType.KEYWORD),
                              ("doc_id", models.PayloadSchemaType.KEYWORD),
                              ("source", models.PayloadSchemaType.KEYWORD),
                              ("position", models.PayloadSchemaType.INTEGER),
                              ("page", models.PayloadSchemaType.INTEGER)):
            self._client.create_payload_index(self._collection, field_name=field,
                                              field_schema=schema)

    def _validate_dims(self, spec: IndexSpec) -> None:
        existing = self.vector_dims()
        for name, dims in {**spec.vectors, **spec.multivectors}.items():
            if name not in existing:
                raise MadoshoError(
                    f"collection '{self._collection}' exists but has no vector "
                    f"'{name}' (existing: {sorted(existing)}); drop the collection "
                    f"or fix the config")
            if existing[name] != dims:
                raise MadoshoError(
                    f"vector '{name}': config wants {dims} dims but collection "
                    f"'{self._collection}' has {existing[name]} — embedder/collection "
                    f"mismatch; drop the collection or fix the config")
        if SPARSE_INDEX in spec.indexes:
            sparse = self._client.get_collection(self._collection).config.params.sparse_vectors or {}
            if SPARSE_INDEX not in sparse:
                raise MadoshoError(
                    f"collection '{self._collection}' exists but has no "
                    f"'{SPARSE_INDEX}' sparse index; drop the collection or "
                    f"fix the config")

    def vector_dims(self) -> dict[str, int]:
        """Dims metadata from the live collection (named vector -> size)."""
        params = self._client.get_collection(self._collection).config.params
        vectors = params.vectors or {}
        if not isinstance(vectors, dict):
            raise MadoshoError(
                f"collection '{self._collection}' uses an unnamed vector layout "
                f"this store cannot manage; drop the collection or use a "
                f"dedicated one")
        return {name: vp.size for name, vp in vectors.items()}

    def _require_schema(self) -> IndexSpec:
        if self._spec is None:
            raise MadoshoError("ensure_schema() must run before using the store")
        return self._spec

    # -- rows <-> chunks ---------------------------------------------------------

    @staticmethod
    def _payload(c: Chunk) -> dict:
        return {"id": c.id, "doc_id": c.doc_id, "text": c.text,
                "context_prefix": c.context_prefix, "position": c.position,
                "page": c.page, "source": c.metadata.get("source", ""),
                "metadata": dict(c.metadata)}

    @staticmethod
    def _chunk(payload: dict) -> Chunk:
        return Chunk(id=payload["id"], doc_id=payload["doc_id"], text=payload["text"],
                     context_prefix=payload["context_prefix"],
                     position=payload["position"], page=payload["page"],
                     metadata=dict(payload.get("metadata") or {}))

    def _hits(self, points, source_index: str) -> list[Hit]:
        return [Hit(chunk_id=p.payload["id"], score=float(p.score),
                    source_index=source_index, chunk=self._chunk(p.payload))
                for p in points]

    # -- store protocol -----------------------------------------------------------

    def upsert(self, chunks: list[EmbeddedChunk]) -> None:
        from qdrant_client import models

        spec = self._require_schema()
        if not chunks:
            return
        points = []
        for ec in chunks:
            vector: dict = {}
            for name in spec.vectors:
                if name not in ec.vectors:
                    raise MadoshoError(f"chunk '{ec.chunk.id}' is missing vector '{name}' "
                                     f"declared in IndexSpec.vectors")
                vector[name] = ec.vectors[name]
            for name in spec.multivectors:
                if name not in ec.multivectors:
                    raise MadoshoError(f"chunk '{ec.chunk.id}' is missing multivector "
                                     f"'{name}' declared in IndexSpec.multivectors")
                vector[name] = ec.multivectors[name]
            if SPARSE_INDEX in spec.indexes:
                # index embed_text (incl. context prefix), matching FakeStore's
                # deliberate choice; rerankers later score body text only
                indices, values = encode_document(ec.chunk.embed_text)
                vector[SPARSE_INDEX] = models.SparseVector(indices=indices, values=values)
            points.append(models.PointStruct(id=_point_id(ec.chunk.id), vector=vector,
                                             payload=self._payload(ec.chunk)))
        self._client.upsert(self._collection, points=points, wait=True)

    def delete(self, doc_ids: list[str]) -> None:
        from qdrant_client import models

        self._require_schema()
        if not doc_ids:
            return
        self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="doc_id",
                                      match=models.MatchAny(any=list(doc_ids)))])),
            wait=True)

    def keyword_search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        from qdrant_client import models

        spec = self._require_schema()
        if SPARSE_INDEX not in spec.indexes:
            raise MadoshoError("keyword_search needs the 'bm25' index, but the "
                             "collection was created without it")
        flt = _to_filter(filters)
        if flt is _IMPOSSIBLE:
            return []
        indices, values = encode_query(query)
        if not indices:
            return []
        res = self._client.query_points(
            self._collection,
            query=models.SparseVector(indices=indices, values=values),
            using=SPARSE_INDEX, limit=k, query_filter=flt, with_payload=True)
        return self._hits(res.points, "bm25")

    def semantic_search(self, vector: Vector, k: int, filters: Filters | None = None) -> list[Hit]:
        self._require_schema()
        flt = _to_filter(filters)
        if flt is _IMPOSSIBLE:
            return []
        res = self._client.query_points(self._collection, query=vector,
                                        using=DENSE_INDEX, limit=k,
                                        query_filter=flt, with_payload=True)
        return self._hits(res.points, "dense")

    def read(self, chunk_ids: list[str], window: int = 0) -> list[Chunk]:
        from qdrant_client import models

        self._require_schema()
        if not chunk_ids:
            return []
        anchors, _ = self._client.scroll(
            self._collection,
            scroll_filter=models.Filter(must=[models.FieldCondition(
                key="id", match=models.MatchAny(any=list(chunk_ids)))]),
            limit=len(chunk_ids), with_payload=True)
        out: dict[str, Chunk] = {}
        for rec in anchors:
            lo = rec.payload["position"] - window
            hi = rec.payload["position"] + window
            offset = None
            while True:
                rows, offset = self._client.scroll(
                    self._collection,
                    scroll_filter=models.Filter(must=[
                        models.FieldCondition(key="doc_id", match=models.MatchValue(
                            value=rec.payload["doc_id"])),
                        models.FieldCondition(key="position", range=models.Range(
                            gte=lo, lte=hi))]),
                    limit=256, with_payload=True, offset=offset)
                for r in rows:
                    c = self._chunk(r.payload)
                    out[c.id] = c
                if offset is None:
                    break
        return sorted(out.values(), key=lambda c: (c.doc_id, c.position))

    # -- MultiVectorSearch extension (kernel spec §5.2) ----------------------------

    def multivector_search(self, name: str, vectors: list[Vector], k: int,
                           filters: Filters | None = None) -> list[Hit]:
        spec = self._require_schema()
        if name not in spec.multivectors:
            raise MadoshoError(f"unknown multivector index '{name}'. "
                             f"Declared: {sorted(spec.multivectors) or 'none'}")
        if not vectors:
            return []
        flt = _to_filter(filters)
        if flt is _IMPOSSIBLE:
            return []
        res = self._client.query_points(self._collection, query=vectors, using=name,
                                        limit=k, query_filter=flt, with_payload=True)
        return self._hits(res.points, name)
