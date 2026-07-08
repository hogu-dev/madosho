"""The one place that reads/writes corpus<->document membership (H2). A document
belongs to many corpora through the document_corpus join; nothing else should
build that query inline."""
from __future__ import annotations

from sqlalchemy import delete, select

from madosho_server import db


def add_membership(session, document_id: int, corpus_id: int) -> None:
    """Idempotent: insert the join row only if it is not already present. Caller commits."""
    exists = session.scalar(select(db.DocumentCorpus).where(
        db.DocumentCorpus.document_id == document_id,
        db.DocumentCorpus.corpus_id == corpus_id))
    if exists is None:
        session.add(db.DocumentCorpus(document_id=document_id, corpus_id=corpus_id))


def member_document_ids(session, corpus_id: int, *,
                        include_generated: bool = True) -> list[int]:
    q = (select(db.Document.id)
         .join(db.DocumentCorpus, db.DocumentCorpus.document_id == db.Document.id)
         .where(db.DocumentCorpus.corpus_id == corpus_id))
    if not include_generated:
        q = q.where(db.Document.origin != "generated")
    return list(session.scalars(q.order_by(db.Document.id)))


def member_documents(session, corpus_id: int, *, indexed_only: bool = False,
                     include_generated: bool = True):
    q = (select(db.Document)
         .join(db.DocumentCorpus, db.DocumentCorpus.document_id == db.Document.id)
         .where(db.DocumentCorpus.corpus_id == corpus_id))
    if indexed_only:
        q = q.where(db.Document.status == "indexed")
    # Work-unit exclusion (stage D): keep a goal's runs from citing their own
    # prior drafts. origin is NOT NULL (default 'source'), so the != test is safe.
    if not include_generated:
        q = q.where(db.Document.origin != "generated")
    return list(session.scalars(q.order_by(db.Document.id)))


def document_corpora(session, document_id: int) -> list[db.Corpus]:
    """The corpora a document belongs to (the membership 'chips'), ordered by id."""
    return list(session.scalars(
        select(db.Corpus)
        .join(db.DocumentCorpus, db.DocumentCorpus.corpus_id == db.Corpus.id)
        .where(db.DocumentCorpus.document_id == document_id)
        .order_by(db.Corpus.id)))


def set_membership_pipelines(session, document_id: int, corpus_id: int,
                             pipeline_ids: list[int]) -> bool:
    """Replace the SET of pipelines THIS corpus queries the document through (H: a
    corpus may fan a document out across several pipelines). An empty list clears the
    selection -> resolution falls back to the document's default. Returns False if the
    document is not a member. Ids are NOT validated here -- a stale/non-indexed id is
    tolerated and skipped at resolve time. Caller commits."""
    member = session.scalar(select(db.DocumentCorpus).where(
        db.DocumentCorpus.document_id == document_id,
        db.DocumentCorpus.corpus_id == corpus_id))
    if member is None:
        return False
    session.execute(delete(db.DocumentCorpusPipeline).where(
        db.DocumentCorpusPipeline.document_id == document_id,
        db.DocumentCorpusPipeline.corpus_id == corpus_id))
    for pid in dict.fromkeys(pipeline_ids):          # de-dupe, preserve order
        session.add(db.DocumentCorpusPipeline(
            corpus_id=corpus_id, document_id=document_id, pipeline_id=pid))
    return True


def membership_selections(session, corpus_id: int) -> dict[int, list[int]]:
    """document_id -> the list of selected pipeline_ids for every (corpus, doc) that
    has an explicit selection. A document with no entry uses its default pipeline."""
    rows = session.execute(
        select(db.DocumentCorpusPipeline.document_id, db.DocumentCorpusPipeline.pipeline_id)
        .where(db.DocumentCorpusPipeline.corpus_id == corpus_id)
        .order_by(db.DocumentCorpusPipeline.id)).all()
    out: dict[int, list[int]] = {}
    for doc_id, pid in rows:
        out.setdefault(doc_id, []).append(pid)
    return out


def remove_membership(session, document_id: int, corpus_id: int) -> None:
    """Drop the join row if present (idempotent). Never deletes the document
    itself - removing the last membership leaves the doc in the library (H4).
    Caller commits."""
    session.execute(delete(db.DocumentCorpusPipeline).where(
        db.DocumentCorpusPipeline.document_id == document_id,
        db.DocumentCorpusPipeline.corpus_id == corpus_id))
    session.execute(delete(db.DocumentCorpus).where(
        db.DocumentCorpus.document_id == document_id,
        db.DocumentCorpus.corpus_id == corpus_id))
