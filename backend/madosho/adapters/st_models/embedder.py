import numpy as np
from pydantic import BaseModel, Field

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Vector


class StEmbedder(ComponentBase):
    """Any sentence-transformers embedding model; default is the Tier B pick."""

    META = ComponentMeta(
        name="granite-embedding-english-r2", kind=ComponentKind.EMBEDDER,
        version="r2", license="Apache-2.0", org="IBM", org_country="US",
        base_lineage=["ModernBERT (US)"], origin_tier=OriginTier.US_SRC,
        hardware=Hardware.CPU, install_extra="models")

    class Options(BaseModel):
        model_id: str = "ibm-granite/granite-embedding-english-r2"
        batch_size: int = Field(default=32, gt=0)
        # Some models (nomic, stella, a few Qwen variants) ship custom modeling
        # code on the Hub and won't load without this. Off by default; each
        # subclass that needs it flips its own default to True.
        trust_remote_code: bool = False

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        from sentence_transformers import SentenceTransformer  # deferred: heavy import

        self.options = options or self.Options()
        self.runtime = runtime
        device = runtime.device if runtime else "cpu"
        cache = str(runtime.cache_dir) if runtime and runtime.cache_dir else None
        self._model = SentenceTransformer(self.options.model_id, device=device,
                                          cache_folder=cache,
                                          trust_remote_code=self.options.trust_remote_code)
        # get_embedding_dimension is the current API (get_sentence_embedding_dimension deprecated)
        self.dims = self._model.get_embedding_dimension()

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    @property
    def native(self):
        return self._model

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        # encode with float32 normalization, then re-normalize in float64 to satisfy
        # the unit-norm contract (float32 accumulated error can reach ~5e-3 at 768 dims)
        vecs = self._model.encode(
            texts, batch_size=self.options.batch_size,
            normalize_embeddings=True, convert_to_numpy=True).astype(np.float64)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return (vecs / norms).tolist()


class MiniLmEmbedder(StEmbedder):
    """all-MiniLM-L6-v2: a small, fast, fully permissive sentence-transformers
    baseline. Registered as a SECOND embedder so a pipeline can differ from the
    docling default on the index axis (a different model = a different vector
    space), and so the heterogeneous-embedder retrieval path (query each index
    separately, then RRF-merge) is actually exercised: this model is 384-dim vs
    granite's 768, so the two pipelines' Qdrant collections are genuinely
    different shapes. All behaviour (load, embed, L2-normalize, dims) is inherited
    from StEmbedder -- only the default model id and the metadata card change."""

    META = ComponentMeta(
        name="all-minilm-l6-v2", kind=ComponentKind.EMBEDDER, version="1.0",
        license="Apache-2.0", org="Sentence-Transformers (UKP Lab)",
        org_country="DE", base_lineage=["MiniLM (Microsoft)"],
        origin_tier=OriginTier.ALLIED_SRC, hardware=Hardware.CPU,
        install_extra="models")

    class Options(StEmbedder.Options):
        model_id: str = "sentence-transformers/all-MiniLM-L6-v2"


# --- Additional embedders -------------------------------------------------
# Each is the same SentenceTransformer machinery with a different default
# model id + metadata card (license/origin are LABELS, never gates). They
# widen the index-axis variety so pipelines can genuinely compete, and span
# multiple vector dimensions/spaces so the heterogeneous-embedder RRF path is
# exercised. Weights download on first use into the HF cache; the org/license
# shown is informational. origin_tier is recorded honestly (CN_OTH_SRC for
# China/other-source models) but does not restrict selection.


class E5LargeInstructEmbedder(StEmbedder):
    """intfloat/multilingual-e5-large-instruct: Microsoft, MIT, 1024-dim,
    strong multilingual. Plain XLM-R, no remote code."""

    META = ComponentMeta(
        name="multilingual-e5-large-instruct", kind=ComponentKind.EMBEDDER,
        version="1.0", license="MIT", org="Microsoft", org_country="US",
        base_lineage=["XLM-RoBERTa (Meta)"], origin_tier=OriginTier.US_SRC,
        hardware=Hardware.CPU, install_extra="models")

    class Options(StEmbedder.Options):
        model_id: str = "intfloat/multilingual-e5-large-instruct"


# NOTE: bge-base-en-v1.5 (BAAI/CN) and qwen3-embedding-0.6b (Alibaba/CN) are
# CN_OTH_SRC and live in the separate CN/other-source models bundle so that
# excluding them is an install-time choice (see docs/COMPLIANCE.md). The US/DE-developed,
# permissively-licensed embedders stay in-tree.


class NomicEmbedTextV15Embedder(StEmbedder):
    """nomic-ai/nomic-embed-text-v1.5: Nomic (US), Apache-2.0, 768-dim,
    Matryoshka. Ships custom modeling code, so trust_remote_code defaults on."""

    META = ComponentMeta(
        name="nomic-embed-text-v1.5", kind=ComponentKind.EMBEDDER, version="1.5",
        license="Apache-2.0", org="Nomic AI", org_country="US",
        base_lineage=["BERT (Nomic-trained)"], origin_tier=OriginTier.US_SRC,
        hardware=Hardware.CPU, install_extra="models")

    class Options(StEmbedder.Options):
        model_id: str = "nomic-ai/nomic-embed-text-v1.5"
        trust_remote_code: bool = True
