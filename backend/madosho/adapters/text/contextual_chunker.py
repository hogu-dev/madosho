from __future__ import annotations

from pydantic import BaseModel, Field

from madosho.core.errors import ConfigError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import Block, Chunk, Document

from madosho.adapters.text.chunker import RecursiveTextChunker

# Anthropic's "Contextual Retrieval" situate prompt (anthropic.com/news/
# contextual-retrieval). The model is shown the whole document and one chunk,
# and asked for a short blurb locating the chunk in the document. That blurb is
# prepended to the chunk before embedding so the vector and BM25 text carry
# document-level context the raw chunk would otherwise lose. Anthropic measured
# ~49% fewer retrieval misses (~67% with reranking).
DEFAULT_PROMPT = (
    "<document>\n{document}\n</document>\n"
    "Here is the chunk we want to situate within the whole document:\n"
    "<chunk>\n{chunk}\n</chunk>\n"
    "Please give a short succinct context to situate this chunk within the overall "
    "document for the purposes of improving search retrieval of the chunk. Answer "
    "only with the succinct context and nothing else."
)


class ContextualChunker(ComponentBase):
    """A chunker that wraps the recursive-text chunker and enriches each chunk
    with an LLM-generated "situating context" (Anthropic's Contextual Retrieval).

    Why this design (teaching notes):

    - **Wrap, don't replace.** We first run ordinary recursive-text chunking, so
      every chunk already has its heading as ``context_prefix`` and the body text
      is split exactly as the plain chunker would split it. We only *add* the
      situating blurb on top. Retrieval quality comes from the enrichment, not
      from changing how text is cut.

    - **Enrich the prefix, not the body.** The blurb is prepended to
      ``context_prefix``, which ``Chunk.embed_text`` already prepends to the body
      at embed time. So the document-level context rides into both the dense
      vector and the BM25 text, while the stored body stays clean for display.
      No query-side change is needed -- that is the whole point of the technique.

    - **One LLM call per chunk, hard-failing.** Each chunk costs one completion.
      The whole document text is sent every call so a provider with prompt
      caching pays for it once; without caching it is simply N calls (the known
      cost of the technique). If any call fails the build is aborted with a
      ConfigError: a silently un-enriched index is indistinguishable from a
      fully-enriched one, so swallowing the error hides a broken pipeline.

    - **Provider-agnostic.** The chunker calls ``runtime.llm`` (a plain
      ``prompt -> str`` callable the service injects). It never names a provider.
      If no llm is wired in, chunking fails clearly instead of silently producing
      un-enriched chunks that would look identical to the plain chunker.

    Pluggable base chunkers (e.g. docling-hybrid) are a later enhancement: that
    needs registry access on the RuntimeContext, a bigger seam than this.
    """

    META = ComponentMeta(
        name="contextual", kind=ComponentKind.CHUNKER, version="0.1.0",
        license="Apache-2.0", org="madosho", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra=None)

    class Options(BaseModel):
        max_chars: int = Field(default=1200, gt=0)
        overlap: int = Field(default=150, ge=0)
        # Documents longer than this skip enrichment entirely (keeping their base
        # heading prefixes) rather than blowing the LLM context window or running
        # up a large bill on a pathologically large file.
        max_doc_chars: int = Field(default=100_000, gt=0)
        prompt_template: str = DEFAULT_PROMPT
        # Which configured LLM endpoint to situate chunks with. The kernel itself
        # ignores this (it calls whatever runtime.llm the host injected); the
        # SERVICE reads it from the recipe to pick which registry endpoint to bind
        # as runtime.llm for this build. None -> the host's default index-time LLM.
        llm_endpoint: str | None = None

    def __init__(self, options: Options | None = None,
                 runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime
        # the base does the actual splitting; pass through the sizing options
        self._base = RecursiveTextChunker(
            options=RecursiveTextChunker.Options(
                max_chars=self.options.max_chars, overlap=self.options.overlap),
            runtime=runtime)

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def chunk(self, doc: Document) -> list[Chunk]:
        chunks = self._base.chunk(doc)
        if not chunks:
            return chunks

        llm = getattr(self.runtime, "llm", None)
        if llm is None:
            raise ConfigError(
                "chunker 'contextual' needs an index-time LLM provider, but none "
                "is configured (runtime.llm is None). Configure an LLM provider for "
                "the ingest lane, or pick a non-contextual chunker.")

        doc_text = self._doc_text(doc)
        if len(doc_text) > self.options.max_doc_chars:
            # too large to situate; keep the base prefixes and skip the LLM calls
            self._log(f"document {doc.doc_id} exceeds max_doc_chars "
                      f"({len(doc_text)} > {self.options.max_doc_chars}); "
                      "skipping contextual enrichment")
            return chunks

        for c in chunks:
            prompt = self.options.prompt_template.format(document=doc_text, chunk=c.text)
            # Fail loudly, do NOT degrade. A single unreachable/failed LLM call
            # aborts the build: a silently un-enriched index looks identical to a
            # good one, so swallowing the error hides a broken pipeline. (Was a
            # soft per-chunk continue; reversed deliberately.)
            try:
                context = (llm(prompt) or "").strip()
            except Exception as e:  # noqa: BLE001
                raise ConfigError(
                    f"contextual chunker: index-time LLM call failed ({e}). The "
                    "configured LLM endpoint is unreachable or erroring; fix the "
                    "endpoint or pick a non-contextual chunker.") from e
            if context:
                # keep the base heading prefix underneath the situated context
                c.context_prefix = (
                    f"{context}\n{c.context_prefix}" if c.context_prefix else context)
        return chunks

    def _doc_text(self, doc: Document) -> str:
        return "\n\n".join(b.content for b in doc.blocks if isinstance(b, Block) and b.content)

    def _log(self, message: str) -> None:
        if self.runtime is not None:
            self.runtime.logger.warning(message)
