from madosho.core.types import Chunk, Hit
from madosho_server import db, membership, retrieval


def _setup(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'r.db'}"); db.create_all()
    s = db.SessionLocal()
    c = db.Corpus(name="c", config={"corpus": "c", "query": []})
    s.add(c); s.commit(); s.refresh(c)
    return s, c


def _doc(s, c, name, status="indexed"):
    d = db.Document(filename=name, content_hash=name,
                    file_uri="u", mimetype="application/pdf", status=status)
    s.add(d); s.commit(); s.refresh(d)
    membership.add_membership(s, d.id, c.id); s.commit()
    return d


def _pipeline(s, c, d, name, score, status="indexed"):
    p = db.Pipeline(document_id=d.id, name=name, config={}, status=status)
    s.add(p); s.commit(); s.refresh(p)
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                             candidate_config=name, score=score, source="static"))
    s.commit()
    return p


class _FakeCorpus:
    """Returns one hit per id in a fixed order; ids encode the pipeline."""
    def __init__(self, ids):
        self._ids = ids

    def query(self, text):
        return [Hit(chunk_id=i, score=1.0, source_index="rrf",
                    chunk=Chunk(id=i, doc_id="kd", text=f"text {i}", page=1,
                                position=0, metadata={"source": "/x.pdf"}))
                for i in self._ids]


def test_rrf_merge_orders_by_summed_reciprocal_rank():
    def ph(pid, cid, lst_pos):
        h = Hit(chunk_id=cid, score=0.0, source_index="x",
                chunk=Chunk(id=cid, doc_id="d", text="t", position=0))
        return retrieval.PipelineHit(h, pid, f"p{pid}", pid)
    list_a = [ph(1, "a1", 0), ph(1, "a2", 1)]
    list_b = [ph(2, "b1", 0)]
    merged = retrieval.rrf_merge([list_a, list_b])
    # a1 and b1 are both rank 0 -> equal RRF; a2 is rank 1 -> lower. a2 last.
    assert merged[-1].hit.chunk_id == "a2"
    assert [m.hit.chunk_id for m in merged[:2]] == ["a1", "b1"]   # tie-break: lower pipeline_id first


def test_single_pipeline_returns_stack_output_unmerged(tmp_path):
    s, c = _setup(tmp_path)
    d = _doc(s, c, "only.pdf")
    p = _pipeline(s, c, d, "only_docling", 5.0)
    corpora = {p.id: _FakeCorpus(["x1", "x2", "x3"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id])
    assert [r.hit.chunk_id for r in res] == ["x1", "x2", "x3"]   # order preserved
    assert all(r.pipeline_name == "only_docling" for r in res)


def test_corpus_query_fans_across_documents_effective_pipelines(tmp_path):
    s, c = _setup(tmp_path)
    d1 = _doc(s, c, "contract.pdf"); d2 = _doc(s, c, "policy.pdf")
    p1lo = _pipeline(s, c, d1, "contract_fast", 3.0)
    p1hi = _pipeline(s, c, d1, "contract_docling", 8.0)     # effective for d1
    p2 = _pipeline(s, c, d2, "policy_docling", 7.0)         # effective for d2
    corpora = {p1lo.id: _FakeCorpus(["fast"]),
               p1hi.id: _FakeCorpus(["c1"]),
               p2.id: _FakeCorpus(["p1"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id])
    names = {r.pipeline_name for r in res}
    assert names == {"contract_docling", "policy_docling"}  # one per doc, highest-rated
    assert "contract_fast" not in names
    # attribution: each hit carries its pipeline + document
    by_name = {r.pipeline_name: r for r in res}
    assert by_name["contract_docling"].document_id == d1.id


def test_pipeline_override_supersedes_effective_for_named_doc(tmp_path):
    s, c = _setup(tmp_path)
    d1 = _doc(s, c, "contract.pdf"); d2 = _doc(s, c, "policy.pdf")
    p1hi = _pipeline(s, c, d1, "contract_docling", 8.0)
    p1ol = _pipeline(s, c, d1, "contract_olmocr", 7.0)
    p2 = _pipeline(s, c, d2, "policy_docling", 7.0)
    corpora = {p1hi.id: _FakeCorpus(["c-doc"]), p1ol.id: _FakeCorpus(["c-ol"]),
               p2.id: _FakeCorpus(["p"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id],
        pipeline_names=["contract_olmocr"])
    names = {r.pipeline_name for r in res}
    assert names == {"contract_olmocr", "policy_docling"}   # d1 overridden, d2 effective


def test_unknown_pipeline_name_raises(tmp_path):
    from madosho.core.errors import MadoshoError
    import pytest
    s, c = _setup(tmp_path)
    d = _doc(s, c, "a.pdf"); _pipeline(s, c, d, "a_docling", 5.0)
    with pytest.raises(MadoshoError):
        retrieval.multi_pipeline_query(
            s, c, "q", open_pipeline=lambda pl: _FakeCorpus(["x"]),
            pipeline_names=["does_not_exist"])


def test_top_k_truncates_merged_results(tmp_path):
    s, c = _setup(tmp_path)
    d1 = _doc(s, c, "a.pdf"); d2 = _doc(s, c, "b.pdf")
    p1 = _pipeline(s, c, d1, "a_docling", 5.0)
    p2 = _pipeline(s, c, d2, "b_docling", 5.0)
    corpora = {p1.id: _FakeCorpus(["a1", "a2"]), p2.id: _FakeCorpus(["b1", "b2"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id], top_k=2)
    assert len(res) == 2


def test_document_with_no_indexed_pipeline_is_skipped(tmp_path):
    s, c = _setup(tmp_path)
    d1 = _doc(s, c, "good.pdf"); d2 = _doc(s, c, "pending.pdf")
    good = _pipeline(s, c, d1, "good_docling", 5.0)
    _pipeline(s, c, d2, "pending_docling", 4.0, status="building")   # not indexed
    corpora = {good.id: _FakeCorpus(["g1"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id])
    assert {r.pipeline_name for r in res} == {"good_docling"}
