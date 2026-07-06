"""Per-corpus pipeline selection: a corpus queries each member document through the
pipelines selected for it (it may select SEVERAL -- they fan out and RRF-merge), or the
document's default (effective) pipeline when nothing is selected."""
from fastapi.testclient import TestClient

from madosho_server import api, db, membership, retrieval


def _client(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'pin.db'}")
    db.create_all()
    return TestClient(api.app)


def _corpus(session, name="aerospace"):
    c = db.Corpus(name=name, config={})
    session.add(c)
    session.flush()
    return c


def _doc(session, filename, status="indexed"):
    d = db.Document(filename=filename, content_hash=filename, file_uri=f"/{filename}",
                    mimetype="application/pdf", status=status)
    session.add(d)
    session.flush()
    return d


def _pipe(session, doc_id, name, *, status="indexed", is_default=False):
    p = db.Pipeline(document_id=doc_id, name=name, status=status, is_default=is_default,
                    collection=f"col_{name}")
    session.add(p)
    session.flush()
    return p


# ---- resolution (retrieval._resolve) ---------------------------------------

def test_resolve_uses_default_when_unselected(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        p1 = _pipe(s, doc.id, "docling", is_default=True)       # lowest id -> default w/o ratings
        _pipe(s, doc.id, "vision")
        membership.add_membership(s, doc.id, c.id)
        s.commit()
        chosen = retrieval._resolve(s, c.id, {})
        assert [p.id for p in chosen] == [p1.id]


def test_resolve_honors_a_single_selection(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        _pipe(s, doc.id, "docling", is_default=True)
        vision = _pipe(s, doc.id, "vision")
        membership.add_membership(s, doc.id, c.id)
        membership.set_membership_pipelines(s, doc.id, c.id, [vision.id])
        s.commit()
        chosen = retrieval._resolve(s, c.id, {})
        assert [p.id for p in chosen] == [vision.id]            # the pick, not the default


def test_resolve_fans_out_across_multiple_selected(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        docling = _pipe(s, doc.id, "docling", is_default=True)
        vision = _pipe(s, doc.id, "vision")
        membership.add_membership(s, doc.id, c.id)
        membership.set_membership_pipelines(s, doc.id, c.id, [docling.id, vision.id])
        s.commit()
        chosen = retrieval._resolve(s, c.id, {})
        assert {p.id for p in chosen} == {docling.id, vision.id}   # both queried -> RRF merge


def test_resolve_skips_stale_selection_and_keeps_valid(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        _pipe(s, doc.id, "docling", is_default=True)
        good = _pipe(s, doc.id, "vision")
        building = _pipe(s, doc.id, "router", status="building")   # not indexed
        membership.add_membership(s, doc.id, c.id)
        membership.set_membership_pipelines(s, doc.id, c.id, [good.id, building.id])
        s.commit()
        chosen = retrieval._resolve(s, c.id, {})
        assert [p.id for p in chosen] == [good.id]              # unbuilt id dropped, good kept


def test_resolve_falls_back_when_all_selected_are_stale(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        default = _pipe(s, doc.id, "docling", is_default=True)
        building = _pipe(s, doc.id, "vision", status="building")   # not indexed
        membership.add_membership(s, doc.id, c.id)
        membership.set_membership_pipelines(s, doc.id, c.id, [building.id])
        s.commit()
        chosen = retrieval._resolve(s, c.id, {})
        assert [p.id for p in chosen] == [default.id]           # empty-after-filter -> default


def test_remove_membership_clears_selection(tmp_path):
    _client(tmp_path)
    with db.SessionLocal() as s:
        c, doc = _corpus(s), _doc(s, "f35.pdf")
        vision = _pipe(s, doc.id, "vision", is_default=True)
        membership.add_membership(s, doc.id, c.id)
        membership.set_membership_pipelines(s, doc.id, c.id, [vision.id])
        s.commit()
        membership.remove_membership(s, doc.id, c.id)
        s.commit()
        assert membership.membership_selections(s, c.id) == {}


# ---- API -------------------------------------------------------------------

def test_members_lists_pipelines_and_selection(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            c, doc = _corpus(s), _doc(s, "f35.pdf")
            d1 = _pipe(s, doc.id, "docling", is_default=True)
            vision = _pipe(s, doc.id, "vision")
            membership.add_membership(s, doc.id, c.id)
            membership.set_membership_pipelines(s, doc.id, c.id, [d1.id, vision.id])
            s.commit()
            cid, did, d1_id, vid = c.id, doc.id, d1.id, vision.id
        members = client.get(f"/corpora/{cid}/members").json()
        assert len(members) == 1
        m = members[0]
        assert m["document_id"] == did and m["filename"] == "f35.pdf"
        assert set(m["selected_pipeline_ids"]) == {d1_id, vid}
        assert m["default_pipeline_id"] == d1_id                # lowest-id, unrated
        assert {p["name"] for p in m["pipelines"]} == {"docling", "vision"}
    finally:
        api.app.dependency_overrides.clear()


def test_put_select_then_clear(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            c, doc = _corpus(s), _doc(s, "f35.pdf")
            docling = _pipe(s, doc.id, "docling", is_default=True)
            vision = _pipe(s, doc.id, "vision")
            membership.add_membership(s, doc.id, c.id)
            s.commit()
            cid, did, d_id, v_id = c.id, doc.id, docling.id, vision.id
        assert client.put(f"/corpora/{cid}/documents/{did}/pipelines",
                          json={"pipeline_ids": [d_id, v_id]}).status_code == 204
        got = client.get(f"/corpora/{cid}/members").json()[0]["selected_pipeline_ids"]
        assert set(got) == {d_id, v_id}
        # clear -> back to default (empty selection)
        assert client.put(f"/corpora/{cid}/documents/{did}/pipelines",
                          json={"pipeline_ids": []}).status_code == 204
        assert client.get(f"/corpora/{cid}/members").json()[0]["selected_pipeline_ids"] == []
    finally:
        api.app.dependency_overrides.clear()


def test_put_select_rejects_foreign_pipeline(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            c = _corpus(s)
            a, b = _doc(s, "a.pdf"), _doc(s, "b.pdf")
            a_pipe = _pipe(s, a.id, "docling", is_default=True)
            b_pipe = _pipe(s, b.id, "docling", is_default=True)
            membership.add_membership(s, a.id, c.id)
            s.commit()
            cid, a_id, a_pipe_id, b_pipe_id = c.id, a.id, a_pipe.id, b_pipe.id
        # one of the ids belongs to doc b -> 422, nothing persisted
        r = client.put(f"/corpora/{cid}/documents/{a_id}/pipelines",
                       json={"pipeline_ids": [a_pipe_id, b_pipe_id]})
        assert r.status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def test_put_select_non_member_is_404(tmp_path):
    client = _client(tmp_path)
    try:
        with db.SessionLocal() as s:
            c, doc = _corpus(s), _doc(s, "f35.pdf")
            p = _pipe(s, doc.id, "docling", is_default=True)    # doc exists but NOT a member
            s.commit()
            cid, did, pid = c.id, doc.id, p.id
        r = client.put(f"/corpora/{cid}/documents/{did}/pipelines", json={"pipeline_ids": [pid]})
        assert r.status_code == 404
    finally:
        api.app.dependency_overrides.clear()
