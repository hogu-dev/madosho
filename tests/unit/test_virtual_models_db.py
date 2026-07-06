import pytest
from sqlalchemy.exc import IntegrityError

from madosho_server import db


def test_virtual_model_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_all()
    with db.SessionLocal() as session:
        corpus = db.Corpus(name="contracts", config={"corpus": "contracts", "query": []})
        session.add(corpus)
        session.commit()
        session.refresh(corpus)
        vm = db.VirtualModel(name="contracts@local", corpus_id=corpus.id,
                             provider="ollama", model="llama3.1",
                             template="Context:\n{context}\n")
        session.add(vm)
        session.commit()
        session.refresh(vm)

    with db.SessionLocal() as session:
        got = session.get(db.VirtualModel, vm.id)
        assert got.name == "contracts@local"
        assert got.provider == "ollama"
        assert got.model == "llama3.1"
        assert "{context}" in got.template


def test_virtual_model_name_is_unique(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path / 'u.db'}")
    db.create_all()
    with db.SessionLocal() as session:
        corpus = db.Corpus(name="c", config={})
        session.add(corpus)
        session.commit()
        session.add(db.VirtualModel(name="dup", corpus_id=corpus.id,
                                    provider="p", model="m"))
        session.commit()
        session.add(db.VirtualModel(name="dup", corpus_id=corpus.id,
                                    provider="p", model="m"))
        with pytest.raises(IntegrityError):
            session.commit()
