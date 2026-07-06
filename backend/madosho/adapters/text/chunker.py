from __future__ import annotations

from pydantic import BaseModel, Field

from madosho.core.meta import ComponentKind, ComponentMeta, Hardware, OriginTier
from madosho.core.protocols import ComponentBase, RuntimeContext
from madosho.core.types import BlockKind, Chunk, Document


def _normalize_ws(text: str) -> str:
    """Collapse runs of whitespace into single spaces. Kept local (rather than
    reusing the docling parser's helper) so this chunker pulls in zero docling
    code -- the whole point of a non-docling lane."""
    return " ".join(text.split())


class RecursiveTextChunker(ComponentBase):
    """A plain-text chunker that works on ``Document.blocks`` instead of a
    parser's native DoclingDocument. It is the non-docling counterpart to
    ``docling-hybrid``: any parser that fills ``.blocks`` (e.g. ``pypdfium2``)
    can feed it, which is what lets us build a fully non-docling
    extract -> chunk -> index pipeline to compare against the docling default.

    Why this design (teaching notes, since chunking choices drive retrieval
    quality):

    - **Recursive separators.** We join the body text of a heading section, then
      split on progressively weaker separators -- paragraph (``\\n\\n``), line
      (``\\n``), sentence (``. ``), word (`` ``), and finally a hard character
      cut. Trying the strongest separator first keeps whole paragraphs and
      sentences together; we only fall back to a cruder split when a single unit
      is itself too big. The alternative (a blind fixed-width cut) slices through
      sentences and hurts both embedding quality and what a reader sees in a hit.

    - **Overlap.** Adjacent chunks share a small character tail. A fact that
      lands right on a chunk boundary would otherwise be retrievable from neither
      side cleanly; the overlap means it shows up in both. The cost is mild
      duplication; the win is recall, which is the usual trade for RAG chunking.

    - **Characters, not tokens.** Size is measured in characters to stay
      dependency-free (no tokenizer download). The rough rule of thumb is ~4
      chars per token, so the defaults (1200 / 150) are about ~300 tokens with
      ~40 tokens of overlap. Swap to a token budget later if a model's context
      math needs to be exact.

    - **Headings scope chunks.** A heading closes the previous section and
      becomes the ``context_prefix`` of the chunks that follow it, mirroring what
      ``docling-hybrid`` does with its heading path. ``context_prefix`` is
      prepended only at embed time (see ``Chunk.embed_text``), so the stored body
      text stays clean.
    """

    META = ComponentMeta(
        name="recursive-text", kind=ComponentKind.CHUNKER, version="0.1.0",
        license="Apache-2.0", org="madosho", org_country="US",
        origin_tier=OriginTier.US_SRC, hardware=Hardware.CPU,
        install_extra=None)

    class Options(BaseModel):
        max_chars: int = Field(default=1200, gt=0)
        overlap: int = Field(default=150, ge=0)

    def __init__(self, options: Options | None = None,
                 runtime: RuntimeContext | None = None):
        self.options = options or self.Options()
        self.runtime = runtime
        if self.options.overlap >= self.options.max_chars:
            # the overlap is meant to be a small tail; if it were a whole chunk
            # wide, seeding the next chunk with it could fail to make progress
            raise ValueError(
                f"overlap ({self.options.overlap}) must be smaller than "
                f"max_chars ({self.options.max_chars})")

    @classmethod
    def make(cls, **options):
        return cls(options=cls.Options(**options))

    def chunk(self, doc: Document) -> list[Chunk]:
        chunks: list[Chunk] = []
        prefix = ""            # current heading path -> context_prefix
        buf: list[str] = []    # body text accumulated under the current heading
        page: int | None = None  # page of the first body block in the buffer

        def flush() -> None:
            nonlocal buf, page
            if not buf:
                return
            body = "\n\n".join(buf)
            for piece in self._split(body):
                idx = len(chunks)
                chunks.append(Chunk(
                    id=f"{doc.doc_id}-{idx:04d}", doc_id=doc.doc_id,
                    text=piece, context_prefix=prefix, position=idx, page=page,
                    metadata={"source": doc.source.path}))
            buf = []
            page = None

        for block in doc.blocks:
            if block.kind == BlockKind.HEADING:
                # close out the previous section so a chunk never spans headings,
                # then adopt this heading as the new context prefix
                flush()
                prefix = _normalize_ws(block.content)
                continue
            content = _normalize_ws(block.content)
            if not content:
                continue
            if page is None:
                page = block.provenance.page
            buf.append(content)
        flush()
        return chunks

    def _split(self, text: str) -> list[str]:
        if len(text) <= self.options.max_chars:
            return [text] if text else []
        return self._pack(self._atoms(text))

    def _atoms(self, text: str) -> list[str]:
        """Break text into the largest pieces that each fit in max_chars, trying
        progressively weaker separators so paragraphs/sentences stay whole."""
        mc = self.options.max_chars
        for sep in ("\n\n", "\n", ". ", " "):
            if sep in text:
                atoms: list[str] = []
                for part in text.split(sep):
                    part = part.strip()
                    if not part:
                        continue
                    if len(part) <= mc:
                        atoms.append(part)
                    else:
                        atoms.extend(self._atoms(part))
                return atoms
        # no separator left (one very long token): hard-cut to the budget
        return [text[i:i + mc] for i in range(0, len(text), mc)]

    def _pack(self, atoms: list[str]) -> list[str]:
        """Greedily pack atoms into chunks <= max_chars, seeding each new chunk
        with a small overlap tail from the previous one. Every atom is already
        <= max_chars, so the result never exceeds the budget."""
        mc, ov = self.options.max_chars, self.options.overlap
        chunks: list[str] = []
        cur = ""
        for atom in atoms:
            cand = f"{cur} {atom}".strip() if cur else atom
            if len(cand) <= mc:
                cur = cand
                continue
            if cur:
                chunks.append(cur)
                tail = cur[-ov:] if ov else ""
                seeded = f"{tail} {atom}".strip() if tail else atom
                cur = seeded if len(seeded) <= mc else atom
            else:
                cur = atom
        if cur:
            chunks.append(cur)
        return chunks
