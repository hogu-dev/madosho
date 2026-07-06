from pydantic import BaseModel, Field

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Hit


class StCrossEncoderReranker(ComponentBase):
    META = ComponentMeta(
        name="granite-reranker-english-r2", kind=ComponentKind.RERANKER,
        version="r2", license="Apache-2.0", org="IBM", org_country="US",
        base_lineage=["ModernBERT (US)"], origin_tier=OriginTier.US_SRC,
        hardware=Hardware.CPU, install_extra="models")

    class Options(BaseModel):
        model_id: str = "ibm-granite/granite-embedding-reranker-english-r2"
        batch_size: int = Field(default=32, gt=0)
        # See StEmbedder.Options.trust_remote_code -- some cross-encoders ship
        # custom modeling code. Off by default; subclasses opt in.
        trust_remote_code: bool = False

    def __init__(self, options: Options | None = None, runtime: RuntimeContext | None = None):
        from sentence_transformers import CrossEncoder  # deferred: heavy import

        self.options = options or self.Options()
        self.runtime = runtime
        device = runtime.device if runtime else "cpu"
        cache = str(runtime.cache_dir) if runtime and runtime.cache_dir else None
        self._model = CrossEncoder(self.options.model_id, device=device,
                                   cache_folder=cache,
                                   trust_remote_code=self.options.trust_remote_code)

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    @property
    def native(self):
        return self._model

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        if not hits:
            return []
        scores = self._model.predict([(query, h.chunk.embed_text) for h in hits],
                                     batch_size=self.options.batch_size)
        rescored = [h.model_copy(update={"score": float(s), "source_index": "rerank"})
                    for h, s in zip(hits, scores)]
        rescored.sort(key=lambda h: (-h.score, h.chunk_id))
        return rescored[:top_k]


# --- Additional rerankers -------------------------------------------------
# All plain sentence-transformers CrossEncoders: same predict/sort machinery,
# different default model id + label. They give the rerank slot real variety
# (it had exactly one option before) so head-to-heads and the eval sweep have
# something to compare. license/origin are labels, not gates. (The generative
# rerankers -- Qwen3-Reranker, mxbai-rerank-v2 -- are deliberately NOT here:
# they don't fit the CrossEncoder.predict shape and need their own adapter.)


# NOTE: bge-reranker-v2-m3 and bge-reranker-base (both BAAI/CN) are
# CN_OTH_SRC and live in the separate CN/other-source models bundle (see
# docs/COMPLIANCE.md). The
# DE-developed, permissively-licensed cross-encoders stay in-tree.


class MsMarcoMiniLmReranker(StCrossEncoderReranker):
    """cross-encoder/ms-marco-MiniLM-L-6-v2: the classic fast English MS MARCO
    cross-encoder (Apache-2.0). Tiny + quick; a good low-latency baseline."""

    META = ComponentMeta(
        name="ms-marco-minilm-l6-v2", kind=ComponentKind.RERANKER, version="2.0",
        license="Apache-2.0", org="Sentence-Transformers (UKP Lab)",
        org_country="DE", base_lineage=["MiniLM (Microsoft)"],
        origin_tier=OriginTier.ALLIED_SRC, hardware=Hardware.CPU,
        install_extra="models")

    class Options(StCrossEncoderReranker.Options):
        model_id: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class MxbaiRerankBaseV1Reranker(StCrossEncoderReranker):
    """mixedbread-ai/mxbai-rerank-base-v1: Mixedbread (Germany), Apache-2.0.
    Allied-org cross-encoder (the v1 family fits CrossEncoder; v2 is generative
    and excluded here)."""

    META = ComponentMeta(
        name="mxbai-rerank-base-v1", kind=ComponentKind.RERANKER, version="1.0",
        license="Apache-2.0", org="Mixedbread", org_country="DE",
        base_lineage=["DeBERTa-v3"], origin_tier=OriginTier.ALLIED_SRC,
        hardware=Hardware.CPU, install_extra="models")

    class Options(StCrossEncoderReranker.Options):
        model_id: str = "mixedbread-ai/mxbai-rerank-base-v1"
