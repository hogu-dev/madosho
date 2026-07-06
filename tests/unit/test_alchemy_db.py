# tests/unit/test_alchemy_db.py
"""AlchemyGoal + AlchemyRun model round-trip and uniqueness constraint."""
import pytest
from sqlalchemy.exc import IntegrityError

from madosho_server import db


def _engine(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'a.db'}")
    db.create_all()
    return db


def test_goal_and_run_roundtrip(tmp_path):
    d = _engine(tmp_path)
    with d.SessionLocal() as s:
        corpus = d.Corpus(name="secdocs")
        s.add(corpus)
        s.flush()
        goal = d.AlchemyGoal(name="find_vuln", corpus_id=corpus.id,
                             goal_type="living-research",
                             spec={"goal": "map the vulns"}, coverage="search")
        s.add(goal)
        s.flush()
        run = d.AlchemyRun(goal_id=goal.id, version=1, status="pending",
                           coverage="search", config={"llm": {"provider": "openai",
                           "model": "m"}}, progress={"phase": "pending"})
        s.add(run)
        s.commit()
        got = s.get(d.AlchemyRun, run.id)
        assert got.version == 1
        assert got.is_final is False
        assert got.usage == {}
        assert got.goal_id == goal.id


def test_goal_name_is_unique(tmp_path):
    d = _engine(tmp_path)
    with d.SessionLocal() as s:
        c = d.Corpus(name="c")
        s.add(c)
        s.flush()
        s.add(d.AlchemyGoal(name="dup", corpus_id=c.id,
                            goal_type="living-research", spec={"goal": "x"},
                            coverage="search"))
        s.commit()
    with d.SessionLocal() as s:
        s.add(d.AlchemyGoal(name="dup", corpus_id=1,
                            goal_type="living-research", spec={"goal": "y"},
                            coverage="search"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_run_sections_roundtrip(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'s.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c1"); s.add(c); s.flush()
        g = db.AlchemyGoal(name="g1", corpus_id=c.id, goal_type="report",
                           spec={"template": "## A\n\nx\n"}, coverage="search")
        s.add(g); s.flush()
        run = db.AlchemyRun(goal_id=g.id, version=1, status="done",
                            coverage="search",
                            sections=[{"key": "a", "title": "A",
                                       "content": "body", "filled": True,
                                       "note": "",
                                       "confidence": {"level": "high"},
                                       "stop_reason": "final",
                                       "llm_calls": 2}])
        s.add(run); s.commit(); rid = run.id
    with db.SessionLocal() as s:
        got = s.get(db.AlchemyRun, rid)
        assert got.sections[0]["key"] == "a"
        assert got.sections[0]["confidence"]["level"] == "high"


def test_run_sections_defaults_empty(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'s2.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        c = db.Corpus(name="c1"); s.add(c); s.flush()
        g = db.AlchemyGoal(name="g1", corpus_id=c.id,
                           goal_type="living-research", spec={"goal": "x"},
                           coverage="search")
        s.add(g); s.flush()
        run = db.AlchemyRun(goal_id=g.id, version=1, status="pending",
                            coverage="search")
        s.add(run); s.commit(); rid = run.id
    with db.SessionLocal() as s:
        assert s.get(db.AlchemyRun, rid).sections == []
