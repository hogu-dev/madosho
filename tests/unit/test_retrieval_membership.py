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
    membership.add_membership(s, d.id, c.id); s.commit()   # scope via the JOIN
    return d


def _pipeline(s, c, d, name, score, status="indexed"):
    p = db.Pipeline(document_id=d.id, name=name, config={}, status=status)
    s.add(p); s.commit(); s.refresh(p)
    s.add(db.TechniqueRating(corpus_id=c.id, document_id=d.id, dimension="embed",
                             candidate_config=name, score=score, source="static"))
    s.commit()
    return p


class _FakeCorpus:
    def __init__(self, ids): self._ids = ids
    def query(self, text):
        return [Hit(chunk_id=i, score=1.0, source_index="rrf",
                    chunk=Chunk(id=i, doc_id="kd", text=f"t{i}", page=1,
                                position=0, metadata={"source": "/x.pdf"}))
                for i in self._ids]


def test_single_document_query_uses_the_docs_effective_pipeline(tmp_path):
    s, c = _setup(tmp_path)
    d = _doc(s, c, "solo.pdf")
    p = _pipeline(s, c, d, "solo_docling", 5.0)
    res = retrieval.single_document_query(
        s, d, "q", open_pipeline=lambda pl: _FakeCorpus(["x1"]))
    assert [r.pipeline_name for r in res] == ["solo_docling"]
    assert all(r.document_id == d.id for r in res)


def test_single_document_query_resolves_named_override_within_doc(tmp_path):
    s, c = _setup(tmp_path)
    d = _doc(s, c, "solo.pdf")
    _pipeline(s, c, d, "solo_docling", 5.0)
    _pipeline(s, c, d, "solo_alt", 1.0)
    res = retrieval.single_document_query(
        s, d, "q", open_pipeline=lambda pl: _FakeCorpus(["x1"]),
        pipeline_names=["solo_alt"])
    assert [r.pipeline_name for r in res] == ["solo_alt"]


def test_single_document_query_empty_when_not_indexed(tmp_path):
    s, c = _setup(tmp_path)
    d = _doc(s, c, "solo.pdf", status="building")   # no indexed pipeline
    res = retrieval.single_document_query(
        s, d, "q", open_pipeline=lambda pl: _FakeCorpus(["x1"]))
    assert res == []


def test_corpus_query_scopes_through_membership_join(tmp_path):
    s, c = _setup(tmp_path)
    other = db.Corpus(name="other", config={}); s.add(other); s.commit()
    d1 = _doc(s, c, "in.pdf")
    d2 = db.Document(filename="out.pdf", content_hash="out",
                     file_uri="u", mimetype="application/pdf", status="indexed")
    s.add(d2); s.commit(); s.refresh(d2)           # NOT a member of c (no join row)
    p1 = _pipeline(s, c, d1, "in_docling", 5.0)
    p2 = _pipeline(s, c, d2, "out_docling", 5.0)
    corpora = {p1.id: _FakeCorpus(["i1"]), p2.id: _FakeCorpus(["o1"])}
    res = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id])
    assert {r.pipeline_name for r in res} == {"in_docling"}   # out.pdf is not a member


def test_member_documents_can_exclude_generated(tmp_path):
    s, c = _setup(tmp_path)
    _doc(s, c, "src.pdf")
    gen = _doc(s, c, "gen.md")
    gen.origin = "generated"; s.commit()
    names = {d.filename for d in membership.member_documents(s, c.id)}
    assert names == {"src.pdf", "gen.md"}          # default includes both
    names_excl = {d.filename for d in
                  membership.member_documents(s, c.id, include_generated=False)}
    assert names_excl == {"src.pdf"}


def test_corpus_query_excludes_generated_when_flagged(tmp_path):
    s, c = _setup(tmp_path)
    d1 = _doc(s, c, "src.pdf")
    d2 = _doc(s, c, "gen.md")
    d2.origin = "generated"; s.commit()
    p1 = _pipeline(s, c, d1, "src_docling", 5.0)
    p2 = _pipeline(s, c, d2, "gen_docling", 5.0)
    corpora = {p1.id: _FakeCorpus(["a"]), p2.id: _FakeCorpus(["b"])}
    incl = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id])
    assert {r.pipeline_name for r in incl} == {"src_docling", "gen_docling"}
    excl = retrieval.multi_pipeline_query(
        s, c, "q", open_pipeline=lambda pl: corpora[pl.id],
        include_generated=False)
    assert {r.pipeline_name for r in excl} == {"src_docling"}
