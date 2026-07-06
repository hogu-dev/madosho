from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field

from madosho.core.errors import ConfigError
from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import BlockKind, Chunk, Document

# Sentence boundary: a .!? followed by whitespace. Deliberately regex, not a
# trained sentence tokenizer (nltk/spaCy), to keep this lane dependency-free like
# RecursiveTextChunker. The tradeoff: abbreviations ("Dr. Smith") can over-split.
# Acceptable -- chunk boundaries are smoothed by the buffer window anyway.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile. Pure-Python (no numpy) -- the value lists
    here are short (one per sentence boundary in a section)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


class SemanticChunker(ComponentBase):
    """Splits text where MEANING shifts, not where a character budget runs out.

    Why this design (teaching notes -- chunking choices drive retrieval quality):

    - **Embed, then find seams.** We split a heading section into sentences,
      embed each one (via the pipeline's own embedder, exposed on
      ``runtime.embedder``), and measure the cosine distance between consecutive
      sentences. A large jump means the topic changed, so we cut there. The win
      over recursive-text is that a chunk holds one coherent idea instead of a
      fixed number of characters that may straddle two topics.

    - **The cost.** This embeds every sentence, so it is ~14x slower than
      character splitting and pays the embedding cost twice (once to chunk, once
      to index). That is inherent to semantic chunking; we surface it, not hide
      it. Pick recursive-text when speed matters more than boundary quality.

    - **Buffer window.** Comparing single sentences is noisy. ``buffer_size``
      blends each sentence with N neighbours on either side before embedding, so
      one stray sentence does not trigger a false cut. 0 = compare raw sentences.

    - **Percentile threshold.** A document's "normal" sentence-to-sentence
      distance varies by writing style, so an absolute cutoff travels badly.
      Instead we cut only where the distance exceeds the ``breakpoint_percentile``
      of that section's own distances -- adaptive per document.

    - **min/max guards.** ``max_chars`` is a hard ceiling so a section that never
      shifts topic does not become one giant chunk (it is then hard-split).
      ``min_chars`` merges a sliver chunk forward so we do not emit single-
      sentence fragments.

    - **Headings scope chunks.** Like recursive-text, a heading closes the prior
      section and becomes the ``context_prefix`` of the chunks under it.

    Needs no ``requires`` entry: every pipeline has an embedder slot, so the
    dependency is always met. The only failure mode -- no runtime embedder wired
    (e.g. constructed bare in a test) -- fails loud below, mirroring the
    contextual chunker's LLM guard.
    """

    META = ComponentMeta(
        name="semantic", kind=ComponentKind.CHUNKER, version="0.1.0",
        license="Apache-2.0", org="madosho", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra=None)

    class Options(BaseModel):
        breakpoint_percentile: float = Field(default=95.0, ge=0, le=100)
        buffer_size: int = Field(default=1, ge=0)
        min_chars: int = Field(default=200, ge=0)
        max_chars: int = Field(default=2000, gt=0)

    def __init__(self, options: "SemanticChunker.Options | None" = None,
                 runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def chunk(self, doc: Document) -> list[Chunk]:
        embedder = getattr(self.runtime, "embedder", None)
        if embedder is None:
            raise ConfigError(
                "chunker 'semantic' needs an index-time embedder, but none is "
                "configured (runtime.embedder is None). This should not happen for "
                "a built pipeline; pick a non-semantic chunker if there is no "
                "embedder.")

        chunks: list[Chunk] = []
        prefix = ""
        buf: list[str] = []
        page: int | None = None

        def flush() -> None:
            nonlocal buf, page
            if not buf:
                return
            body = " ".join(buf)
            for piece in self._segment(body, embedder):
                idx = len(chunks)
                chunks.append(Chunk(
                    id=f"{doc.doc_id}-{idx:04d}", doc_id=doc.doc_id,
                    text=piece, context_prefix=prefix, position=idx, page=page,
                    metadata={"source": doc.source.path}))
            buf = []
            page = None

        for block in doc.blocks:
            if block.kind == BlockKind.HEADING:
                flush()
                prefix = " ".join(block.content.split())
                continue
            content = " ".join(block.content.split())
            if not content:
                continue
            if page is None:
                page = block.provenance.page
            buf.append(content)
        flush()
        return chunks

    def _segment(self, body: str, embedder) -> list[str]:
        sentences = [s.strip() for s in _SENT_SPLIT.split(body) if s.strip()]
        if not sentences:
            return []
        if len(sentences) == 1:
            return self._cap(sentences)

        b = self.options.buffer_size
        windows = [" ".join(sentences[max(0, i - b): i + b + 1])
                   for i in range(len(sentences))]
        vecs = embedder.embed(windows)
        dists = [1.0 - _cosine(vecs[i], vecs[i + 1]) for i in range(len(vecs) - 1)]
        threshold = _percentile(dists, self.options.breakpoint_percentile)

        # build segments, cutting AFTER sentence i when its forward distance is a
        # genuine outlier (strict > so an all-equal section makes no cuts)
        segments: list[list[str]] = []
        cur: list[str] = []
        for i, sent in enumerate(sentences):
            cur.append(sent)
            if i < len(dists) and dists[i] > threshold:
                segments.append(cur)
                cur = []
        if cur:
            segments.append(cur)

        texts = [" ".join(seg) for seg in segments]
        return self._cap(self._merge_small(texts))

    def _merge_small(self, texts: list[str]) -> list[str]:
        """Coalesce chunks below min_chars so we do not emit slivers. We walk
        left to right: whenever the chunk we just kept is still under min_chars,
        the next chunk is appended onto it (a small chunk pulls in its follower)
        rather than starting a new one. A final chunk that is still too small is
        then folded back into the previous one."""
        mn = self.options.min_chars
        if mn <= 0 or len(texts) <= 1:
            return texts
        out: list[str] = []
        for t in texts:
            if out and len(out[-1]) < mn:
                out[-1] = f"{out[-1]} {t}".strip()
            else:
                out.append(t)
        # if the final chunk is still too small, fold it back
        if len(out) > 1 and len(out[-1]) < mn:
            last = out.pop()
            out[-1] = f"{out[-1]} {last}".strip()
        return out

    def _cap(self, texts: list[str]) -> list[str]:
        """Hard-split any chunk over max_chars (a never-shifting section)."""
        mc = self.options.max_chars
        out: list[str] = []
        for t in texts:
            if len(t) <= mc:
                if t:
                    out.append(t)
                continue
            out.extend(t[i:i + mc] for i in range(0, len(t), mc))
        return out
