"""Fast unit tests for the KB CLI parity seam (create/list/get/add/edit/search).

Asserts request SHAPE against a monkeypatched core.http, mirroring the style
in test_madosho_cli.py but at the core.py seam (get_json/post_json take a
single full-url positional arg in this repo's real http.py - no params=/json=
kwargs).
"""
from __future__ import annotations

from madosho_cli import core


def test_get_kb_page_calls_endpoint(monkeypatch):
    calls = {}

    def fake_get(url):
        calls["url"] = url
        return {"type": "concept", "title": "Reranking", "slug": "reranking",
                "description": "d", "tags": [], "timestamp": "", "sources": [],
                "body": "x"}

    monkeypatch.setattr(core.http, "get_json", fake_get)
    out = core.get_kb_page(3, "reranking")
    assert calls["url"].endswith("/kbs/3/pages/reranking")
    assert out["title"] == "Reranking"


def test_add_kb_page_posts_body(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"slug": "chunking"}

    monkeypatch.setattr(core.http, "post_json", fake_post)
    core.add_kb_page(3, type="concept", title="Chunking", description="d",
                     tags=["ir"], sources=["doc:1"], body="b")
    assert captured["url"].endswith("/kbs/3/pages")
    assert captured["payload"]["title"] == "Chunking"
    assert captured["payload"]["tags"] == ["ir"]


def test_save_kb_page_posts_to_corpus_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"kb_id": 5, "slug": "t", "action": "created"}

    monkeypatch.setattr(core.http, "post_json", fake_post)
    core.save_kb_page(7, kb_name="Notes", title="T", body="report")
    assert captured["url"].endswith("/corpora/7/kb-pages")
    assert captured["payload"]["kb_name"] == "Notes"
    assert captured["payload"]["body"] == "report"
    assert captured["payload"]["upsert"] is True


def test_alchemy_save_to_kb_defaults_from_goal(monkeypatch):
    captured = {}

    def fake_get(url):
        if url.endswith("/alchemy/goals/energy-brief"):
            return {"id": 1, "name": "energy-brief", "corpus_id": 9}
        return {"draft_markdown": "# Findings\n\ngrounded [d.md]"}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"kb_id": 2, "slug": "energy-brief", "action": "created"}

    monkeypatch.setattr(core.http, "get_json", fake_get)
    monkeypatch.setattr(core.http, "post_json", fake_post)
    core.alchemy_save_to_kb("energy-brief", 3)
    # corpus, kb name and title all default from the goal
    assert captured["url"].endswith("/corpora/9/kb-pages")
    assert captured["payload"]["kb_name"] == "energy-brief"
    assert captured["payload"]["title"] == "energy-brief"
    assert captured["payload"]["body"] == "# Findings\n\ngrounded [d.md]"
