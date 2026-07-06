from madosho_server import db, membership


def _mk(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'m.db'}")
    db.create_all()
    return db.SessionLocal()


def _corpus(s, name):
    c = db.Corpus(name=name, config={}); s.add(c); s.commit(); s.refresh(c)
    return c


def _doc(s, c, h, status="indexed"):
    d = db.Document(filename=f"{h}.pdf", content_hash=h,
                    file_uri="u", mimetype="application/pdf", status=status)
    s.add(d); s.commit(); s.refresh(d)
    return d


def test_add_membership_is_idempotent(tmp_path):
    s = _mk(tmp_path)
    c = _corpus(s, "c"); d = _doc(s, c, "h1")
    membership.add_membership(s, d.id, c.id)
    membership.add_membership(s, d.id, c.id)   # twice, no duplicate
    s.commit()
    assert s.query(db.DocumentCorpus).count() == 1


def test_member_documents_filters_by_corpus_and_status(tmp_path):
    s = _mk(tmp_path)
    c1 = _corpus(s, "c1"); c2 = _corpus(s, "c2")
    d1 = _doc(s, c1, "h1"); d2 = _doc(s, c1, "h2", status="building")
    d3 = _doc(s, c2, "h3")
    for d, c in [(d1, c1), (d2, c1), (d3, c2)]:
        membership.add_membership(s, d.id, c.id)
    s.commit()
    assert membership.member_document_ids(s, c1.id) == [d1.id, d2.id]
    indexed = membership.member_documents(s, c1.id, indexed_only=True)
    assert [d.id for d in indexed] == [d1.id]   # d2 is "building"


def test_document_corpora_lists_member_corpora_ordered(tmp_path):
    s = _mk(tmp_path)
    c1 = _corpus(s, "c1"); c2 = _corpus(s, "c2"); c3 = _corpus(s, "c3")
    d = _doc(s, c1, "h1")
    membership.add_membership(s, d.id, c2.id)   # member of c2 and c3, NOT c1's join
    membership.add_membership(s, d.id, c3.id)
    s.commit()
    corpora = membership.document_corpora(s, d.id)
    assert [c.name for c in corpora] == ["c2", "c3"]   # ordered by Corpus.id


def test_remove_membership_is_idempotent(tmp_path):
    s = _mk(tmp_path)
    c = _corpus(s, "c"); d = _doc(s, c, "h1")
    membership.add_membership(s, d.id, c.id); s.commit()
    assert s.query(db.DocumentCorpus).count() == 1
    membership.remove_membership(s, d.id, c.id); s.commit()
    assert s.query(db.DocumentCorpus).count() == 0
    membership.remove_membership(s, d.id, c.id); s.commit()   # again, no error
    assert s.query(db.DocumentCorpus).count() == 0
