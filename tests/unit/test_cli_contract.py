"""pin madosho-cli's agent-facing contract - stdout is data-or-empty, errors
go to stderr with non-zero exit, and a missing corpus on `search` surfaces clearly."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from madosho_cli import main as cli_main


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeHttp:
    def __init__(self, routes: dict):
        self.routes = routes

    def __call__(self, req, *a, **kw):
        url = req.full_url
        for key in sorted(self.routes, key=len, reverse=True):
            if key in url:
                val = self.routes[key]
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def fake_http(monkeypatch):
    def install(routes):
        monkeypatch.setattr(urllib.request, "urlopen", _FakeHttp(routes))
    return install


def test_error_writes_nothing_to_stdout(fake_http, capsys):
    # the contract a --json tool driver relies on: on failure, stdout stays empty
    err = urllib.error.HTTPError("http://x/corpora", 500, "boom", {}, io.BytesIO(b"x"))
    fake_http({"/corpora": err})
    rc = cli_main.main(["list-corpora", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""           # nothing parseable on stdout
    assert "HTTP 500" in captured.err   # the error went to stderr


def test_search_missing_corpus_surfaces_clearly(fake_http, capsys):
    # /query rejects an unknown corpus; the CLI must surface it non-zero, stdout empty
    err = urllib.error.HTTPError(
        "http://x/query", 404, "nope", {}, io.BytesIO(b'{"detail":"corpus not found"}'))
    fake_http({"/query": err})
    rc = cli_main.main(["search", "ghost", "anything", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "corpus not found" in captured.err.lower()


def test_search_passes_through_basenamed_source(fake_http, capsys):
    # the server basenames `source`; the CLI must pass it through unmangled
    hit = {"text": "t", "score": 0.9, "citation": "afti.pdf p.1", "source": "afti.pdf",
           "document_id": 3, "position": 1, "pipeline_id": 7, "pipeline": "afti_docling"}
    fake_http({"/query": {"hits": [hit]}})
    rc = cli_main.main(["search", "aerospace", "q", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hits"][0]["source"] == "afti.pdf"   # basename, no directory
    assert "/" not in out["hits"][0]["source"]
