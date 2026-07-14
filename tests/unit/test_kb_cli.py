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
