from research_agent.types import Citation, ToolResult

from alchemy.ledger import (COVERAGE_MODES, CoverageLedger,
                            citations_from_hits, list_corpus_docs)


def _cit(doc_id):
    return Citation(document_id=doc_id, pipeline_id=1, pipeline="p",
                    position=0, citation=f"doc {doc_id} @0", source="s",
                    score=0.9, quote="q")


class ListingTools:
    def __init__(self, data=None, ok=True):
        self.data = data
        self.ok = ok
        self.calls = []

    def invoke(self, name, args):
        self.calls.append((name, args))
        return ToolResult(ok=self.ok, data=self.data,
                          error=None if self.ok else "boom")


def test_coverage_modes_constant():
    assert COVERAGE_MODES == ("search", "full", "exhaustive")


def test_list_corpus_docs_maps_id_to_filename():
    tools = ListingTools(data={"corpus": "c", "documents": [
        {"id": 1, "filename": "a.pdf", "status": "indexed"},
        {"id": 2, "filename": "b.pdf", "status": "indexed"}]})
    docs = list_corpus_docs(tools, "c")
    assert docs == {1: "a.pdf", 2: "b.pdf"}
    assert tools.calls == [("list-documents", {"corpus": "c"})]


def test_list_corpus_docs_failure_returns_none():
    assert list_corpus_docs(ListingTools(ok=False), "c") is None
    assert list_corpus_docs(ListingTools(data="not a dict"), "c") is None


def test_citations_from_hits_mirrors_loop_shape():
    hits = [{"document_id": 3, "pipeline_id": 4, "pipeline": "p",
             "position": 7, "citation": "doc 3 @7", "source": "s.txt",
             "score": 0.5, "text": "x" * 600}]
    cits = citations_from_hits(hits)
    assert len(cits) == 1
    assert cits[0].document_id == 3
    assert cits[0].position == 7
    assert len(cits[0].quote) == 500   # quote capped like the loop's


def test_mark_keeps_strongest_how_and_ignores_none():
    led = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    led.mark(1, "search")
    led.mark(1, "read")
    led.mark(1, "search")          # weaker: must not downgrade
    led.mark(None, "search")       # anonymous citations carry no doc
    assert led.consulted == {1: "read"}


def test_mark_citations_and_unconsulted():
    led = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b", 3: "c"})
    led.mark_citations([_cit(1), _cit(1), _cit(None)])
    assert led.consulted == {1: "search"}
    assert led.unconsulted() == [2, 3]


def test_unconsulted_empty_when_corpus_unknown():
    led = CoverageLedger(mode="full", corpus_docs=None)
    assert led.unconsulted() == []


def test_merge_prior_carries_how_and_flags_origin():
    led = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    led.merge_prior({"consulted": {"1": "read", "junk": "search"}})
    assert led.consulted == {1: "read"}
    assert led.from_prior == {1}


def test_complete_semantics_per_mode():
    # search: no guarantee to check
    assert CoverageLedger(mode="search", corpus_docs={1: "a"}).complete() is None
    # unknown corpus: cannot verify
    assert CoverageLedger(mode="full", corpus_docs=None).complete() is None
    # full: every doc consulted, no failures
    led = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    led.mark(1, "search")
    assert led.complete() is False
    led.mark(2, "forced")
    assert led.complete() is True
    led.failures[2] = "search-doc error"
    assert led.complete() is False
    # exhaustive: every doc must be READ, consulted-by-search is not enough
    led2 = CoverageLedger(mode="exhaustive", corpus_docs={1: "a", 2: "b"})
    led2.mark(1, "read")
    led2.mark(2, "search")
    assert led2.complete() is False
    led2.mark(2, "read")
    assert led2.complete() is True


def test_summary_strings():
    led = CoverageLedger(mode="search", corpus_docs={1: "a", 2: "b", 3: "c"})
    led.mark(1, "search")
    assert led.summary() == "consulted 1 of 3 docs (search-driven)"

    unknown = CoverageLedger(mode="search", corpus_docs=None)
    unknown.mark(1, "search")
    assert unknown.summary() == "consulted 1 docs (corpus size unknown)"

    full = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    full.mark(1, "search")
    full.mark(2, "forced")
    assert full.summary() == "coverage full: consulted 2/2 docs"

    short = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    short.mark(1, "search")
    short.shortfall = "llm call cap"
    assert short.summary() == "coverage full: consulted 1/2 docs (llm call cap)"

    exh = CoverageLedger(mode="exhaustive", corpus_docs={1: "a", 2: "b"})
    exh.mark(1, "read")
    exh.mark(2, "search")
    exh.failures[2] = "get-doc error"
    assert exh.summary() == ("coverage exhaustive: read 1/2 docs "
                             "(1 docs failed)")


def test_to_dict_round_trip_shape():
    led = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    led.mark(1, "search")
    led.merge_prior({"consulted": {"2": "read"}})
    d = led.to_dict()
    assert d["mode"] == "full"
    assert d["total_docs"] == 2
    assert d["consulted"] == {"1": "search", "2": "read"}
    assert d["from_prior"] == [2]
    assert d["unconsulted"] == []
    assert d["failures"] == {}
    assert d["complete"] is True
    assert d["summary"] == "coverage full: consulted 2/2 docs"
    # a later run can merge THIS dict back in (the rerun union chain)
    led2 = CoverageLedger(mode="full", corpus_docs={1: "a", 2: "b"})
    led2.merge_prior(d)
    assert led2.consulted == {1: "search", 2: "read"}
