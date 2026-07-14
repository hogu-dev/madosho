"""Coverage ledger: the mechanical record of which corpus documents a run
consulted.

Extracted from tool traffic exactly the way citations are (from tool results,
never model claims) - that is what makes coverage guarantees CHECKABLE. The
ledger never blocks a run: a failed corpus listing degrades to "corpus size
unknown" reporting, a failed forced retrieval becomes a per-doc failure entry.
Honest shortfall beats a hard stop, because a partial report the user can
rerun is worth more than an error.

"consulted" strength is ordered: search < forced < read. mark() keeps the
strongest evidence seen for a doc, so an exhaustive read is never downgraded
by a later search hit, and the exhaustive guarantee ("every doc READ") can be
verified per doc, not just counted.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from research_agent.types import Citation

COVERAGE_MODES = ("search", "full", "exhaustive")

# how a doc came to be consulted, weakest to strongest evidence
_HOW_ORDER = ("search", "forced", "read")


def list_corpus_docs(tools, corpus: str) -> dict[int, str] | None:
    """Enumerate the corpus mechanically (no LLM call) through the same tool
    surface the work units use - the orchestrator needs the denominator for
    "consulted N of M". None means the listing failed; the ledger then
    reports honestly instead of inventing a corpus size."""
    res = tools.invoke("list-documents", {"corpus": corpus})
    if not getattr(res, "ok", False) or not isinstance(res.data, dict):
        return None
    docs: dict[int, str] = {}
    for d in res.data.get("documents", []):
        if isinstance(d, dict) and isinstance(d.get("id"), int):
            docs[d["id"]] = d.get("filename") or ""
    return docs


def citations_from_hits(hits: list) -> list[Citation]:
    """Citation objects from search-doc hits the ORCHESTRATOR retrieved
    (forced passes). Mirrors the loop's own search mapping (incl. the 500-char
    quote cap) so forced evidence is attributed exactly like unit evidence -
    the loop is frozen, so the tiny mapper is duplicated rather than imported
    from its private helper."""
    out: list[Citation] = []
    for h in hits:
        if not isinstance(h, dict):
            continue
        out.append(Citation(
            document_id=h.get("document_id"), pipeline_id=h.get("pipeline_id"),
            pipeline=h.get("pipeline"), position=h.get("position"),
            citation=h.get("citation") or "", source=h.get("source"),
            score=h.get("score"), quote=(h.get("text") or "")[:500]))
    return out


@dataclass
class CoverageLedger:
    """Per-run coverage state. corpus_docs is id -> filename (None when the
    listing failed). consulted is id -> how ("search"|"forced"|"read");
    from_prior flags ids whose consultation came from the revision chain
    (reruns inherit the union - v2 need not re-consult docs v1 covered).
    failures is id -> why (a doc the run tried but could not get to).
    shortfall is the run-level reason coverage stopped early ("llm call cap",
    "cancelled", ...) - empty when enforcement ran to the end."""
    mode: str
    corpus_docs: dict[int, str] | None
    consulted: dict[int, str] = field(default_factory=dict)
    from_prior: set[int] = field(default_factory=set)
    failures: dict[int, str] = field(default_factory=dict)
    shortfall: str = ""

    def __post_init__(self):
        # Stage E: one reentrant lock for every method that reads or mutates
        # `consulted`. Parallel section units mark citations from N threads
        # (via _run_unit_with_handoffs) while the orchestrator may read the
        # ledger; an unguarded sorted(consulted.items()) mid-insert raises
        # "dictionary changed size during iteration". RLock, not Lock: the
        # public methods compose (to_dict -> unconsulted/complete/summary,
        # complete -> unconsulted) and re-entry on a plain Lock would
        # deadlock. `failures` and `shortfall` are written directly by the
        # forced/mining phases, which run on the orchestrator's own thread
        # outside the parallel window - guarding the methods covers the
        # whole race surface. Not a dataclass field, so repr/eq are
        # untouched.
        self._lock = threading.RLock()

    def mark(self, doc_id, how: str) -> None:
        if doc_id is None:
            return
        with self._lock:
            cur = self.consulted.get(doc_id)
            if cur is None or _HOW_ORDER.index(how) > _HOW_ORDER.index(cur):
                self.consulted[doc_id] = how

    def mark_citations(self, citations: list, how: str = "search") -> None:
        with self._lock:
            for c in citations:
                self.mark(getattr(c, "document_id", None), how)

    def merge_prior(self, prior: dict | None) -> None:
        """Fold a prior run's persisted ledger dict into this one. The prior
        HOW is preserved (an exhaustive rerun must know which docs the chain
        already READ, not just touched); junk keys are skipped, never fatal -
        an old or hand-edited row must not kill a rerun."""
        with self._lock:
            for key, how in ((prior or {}).get("consulted") or {}).items():
                try:
                    doc_id = int(key)
                except (TypeError, ValueError):
                    continue
                if how not in _HOW_ORDER:
                    continue
                self.mark(doc_id, how)
                self.from_prior.add(doc_id)

    def unconsulted(self) -> list[int]:
        if self.corpus_docs is None:
            return []
        with self._lock:
            return sorted(d for d in self.corpus_docs
                          if d not in self.consulted)

    def complete(self) -> bool | None:
        """Was the mode's guarantee met? None = nothing to check (search mode
        promises nothing; an unknown corpus size cannot be verified)."""
        if self.mode == "search" or self.corpus_docs is None:
            return None
        with self._lock:
            if self.failures:
                return False
            if self.mode == "exhaustive":
                return all(self.consulted.get(d) == "read"
                           for d in self.corpus_docs)
            return not self.unconsulted()

    def summary(self) -> str:
        """One honest human sentence - what the spec calls the coverage
        account. Never claims more than the ledger proves."""
        with self._lock:
            if self.corpus_docs is None:
                return f"consulted {len(self.consulted)} docs (corpus size unknown)"
            total = len(self.corpus_docs)
            if self.mode == "search":
                return f"consulted {len(self.consulted)} of {total} docs (search-driven)"
            if self.mode == "exhaustive":
                done = sum(1 for h in self.consulted.values() if h == "read")
                base = f"coverage exhaustive: read {done}/{total} docs"
            else:
                base = f"coverage full: consulted {len(self.consulted)}/{total} docs"
            notes = []
            if self.shortfall:
                notes.append(self.shortfall)
            if self.failures:
                notes.append(f"{len(self.failures)} docs failed")
            return base + (f" ({'; '.join(notes)})" if notes else "")

    def to_dict(self) -> dict:
        """JSON-ready shape persisted on the run row. Keys are strings (JSON
        object keys always are); merge_prior() parses them back, so a stored
        ledger IS the rerun-union input for the next version."""
        with self._lock:
            return {
                "mode": self.mode,
                "total_docs": None if self.corpus_docs is None else len(self.corpus_docs),
                "consulted": {str(k): v for k, v in sorted(self.consulted.items())},
                "from_prior": sorted(self.from_prior),
                "unconsulted": self.unconsulted(),
                "failures": {str(k): v for k, v in sorted(self.failures.items())},
                "complete": self.complete(),
                "shortfall": self.shortfall,
                "summary": self.summary(),
            }
