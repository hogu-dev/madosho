"""Fast unit tests for the madosho CLI.

No live server: urllib.request.urlopen is stubbed with FakeHttp, which routes
canned JSON by URL (longest-matching key first, so /corpora/2/documents wins over
/corpora) and records every request so tests can assert method/url/body.
"""
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


class FakeHttp:
    """Routes urlopen(req) by URL substring to a canned payload (or raises it)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, object]] = []  # (method, url, json-body|None)

    def __call__(self, req, *a, **kw):
        url = req.full_url
        body = json.loads(req.data.decode()) if getattr(req, "data", None) else None
        self.calls.append((req.get_method(), url, body))
        for key in sorted(self.routes, key=len, reverse=True):  # most specific first
            if key in url:
                val = self.routes[key]
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture
def fake_http(monkeypatch):
    def install(routes: dict) -> FakeHttp:
        fh = FakeHttp(routes)
        monkeypatch.setattr(urllib.request, "urlopen", fh)
        return fh

    return install


def test_list_corpora_json(fake_http, capsys):
    fake_http({"/corpora": [
        {"id": 1, "name": "aerospace", "config": {}},
        {"id": 2, "name": "test", "config": {}},
    ]})
    rc = cli_main.main(["list-corpora", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"corpora": [
        {"id": 1, "name": "aerospace"},
        {"id": 2, "name": "test"},
    ]}


def test_list_corpora_human(fake_http, capsys):
    fake_http({"/corpora": [{"id": 7, "name": "aerospace", "config": {}}]})
    rc = cli_main.main(["list-corpora"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aerospace" in out and "7" in out


def test_http_error_exits_nonzero(fake_http, capsys):
    err = urllib.error.HTTPError(
        "http://x/corpora", 404, "nope", {}, io.BytesIO(b"not found")
    )
    fake_http({"/corpora": err})
    rc = cli_main.main(["list-corpora", "--json"])
    assert rc == 1
    assert "HTTP 404" in capsys.readouterr().err


def test_unreachable_exits_nonzero(fake_http, capsys):
    fake_http({"/corpora": urllib.error.URLError("connection refused")})
    rc = cli_main.main(["list-corpora"])
    assert rc == 1
    assert "could not reach" in capsys.readouterr().err


def test_list_documents_resolves_name(fake_http, capsys):
    fake_http({
        "/corpora": [{"id": 2, "name": "aerospace", "config": {}}],
        "/corpora/2/documents": [
            {"id": 3, "corpus_id": 2, "filename": "afti.pdf", "status": "indexed",
             "error": None, "progress": {}, "selected_pipeline_id": None},
            {"id": 4, "corpus_id": 2, "filename": "wavpack.pdf", "status": "indexed",
             "error": None, "progress": {}, "selected_pipeline_id": 10},
        ],
    })
    rc = cli_main.main(["list-documents", "aerospace", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["corpus"] == "aerospace"
    assert [d["id"] for d in out["documents"]] == [3, 4]
    assert out["documents"][0] == {
        "id": 3, "filename": "afti.pdf", "status": "indexed",
        "selected_pipeline_id": None, "origin": "source", "origin_label": "",
    }
    assert out["documents"][1]["selected_pipeline_id"] == 10


def test_list_documents_unknown_corpus_errors(fake_http, capsys):
    fake_http({"/corpora": [{"id": 2, "name": "aerospace", "config": {}}]})
    rc = cli_main.main(["list-documents", "nope", "--json"])
    assert rc == 1
    assert "corpus not found" in capsys.readouterr().err


def test_list_documents_prints_generated_suffix(fake_http, capsys):
    # Stage D: a generated doc's human-readable row gets a "[generated: ...]"
    # suffix carried verbatim from the API's origin_label (no CLI-side
    # formula) - a source row is unaffected.
    fake_http({
        "/corpora": [{"id": 2, "name": "reports", "config": {}}],
        "/corpora/2/documents": [
            {"id": 5, "filename": "src.pdf", "status": "indexed",
             "selected_pipeline_id": None, "origin": "source",
             "origin_label": ""},
            {"id": 6, "filename": "find_vuln-v2.md", "status": "indexed",
             "selected_pipeline_id": None, "origin": "generated",
             "origin_label": "[generated: find_vuln v2]"},
        ],
    })
    rc = cli_main.main(["list-documents", "reports"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "find_vuln-v2.md  [generated: find_vuln v2]" in out
    assert "src.pdf" in out
    assert "src.pdf  [generated" not in out    # source row has no suffix


def test_list_documents_json_carries_origin(fake_http, capsys):
    fake_http({
        "/corpora": [{"id": 2, "name": "reports", "config": {}}],
        "/corpora/2/documents": [
            {"id": 6, "filename": "g.md", "status": "indexed",
             "selected_pipeline_id": None, "origin": "generated",
             "origin_label": "[generated: g v1]"},
        ],
    })
    cli_main.main(["list-documents", "reports", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["documents"][0]["origin"] == "generated"
    assert out["documents"][0]["origin_label"] == "[generated: g v1]"


def _hit(i):
    return {
        "text": f"chunk {i} body text", "score": 1.0 / (i + 1),
        "page": i, "citation": f"afti.pdf p.{i}", "source": "afti.pdf",
        "document_id": 3, "position": i, "pipeline_id": 7, "pipeline": "afti_docling",
    }


def test_search_retrieval_only_and_truncates(fake_http, capsys):
    fh = fake_http({"/query": {"hits": [_hit(i) for i in range(10)]}})
    rc = cli_main.main(["search", "aerospace", "sensor failure", "--top-k", "3", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["hits"]) == 3
    # full hit shape is passed through verbatim (the agent needs it to cite)
    assert out["hits"][0]["pipeline"] == "afti_docling"
    assert out["hits"][0]["document_id"] == 3
    # the request was a retrieval-only POST: correct body, no llm field
    method, url, body = fh.calls[0]
    assert method == "POST" and url.endswith("/query")
    assert body == {"corpus": "aerospace", "prompt": "sensor failure"}
    assert "llm" not in body


def test_search_pipeline_passthrough(fake_http):
    fh = fake_http({"/query": {"hits": []}})
    cli_main.main(["search", "aerospace", "q", "--pipeline", "afti_nodocling", "--json"])
    _, _, body = fh.calls[0]
    assert body["pipelines"] == ["afti_nodocling"]


def test_search_default_top_k_is_8(fake_http, capsys):
    fake_http({"/query": {"hits": [_hit(i) for i in range(20)]}})
    cli_main.main(["search", "aerospace", "q", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert len(out["hits"]) == 8


def test_get_doc_effective_joins_in_position_order(fake_http, capsys):
    fake_http({
        "/documents/5/pipelines": [
            {"id": 9, "name": "wav_docling", "effective": False, "status": "indexed"},
            {"id": 10, "name": "wav_nodocling", "effective": True, "status": "indexed"},
        ],
        "/pipelines/10/artifacts": {
            "document_id": 5,
            "chunks": [
                {"id": "c2", "text": "second", "position": 1, "page": 1},
                {"id": "c1", "text": "first", "position": 0, "page": 1},
            ],
            "tables": [],
        },
    })
    rc = cli_main.main(["get-doc", "5", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pipeline"] == "wav_nodocling"
    assert out["pipeline_id"] == 10
    assert out["text"] == "first\n\nsecond"  # sorted by position, not storage order
    assert out["char_count"] == len("first\n\nsecond")


def test_get_doc_named_pipeline_wins(fake_http):
    fh = fake_http({
        "/documents/5/pipelines": [
            {"id": 9, "name": "wav_docling", "effective": True, "status": "indexed"},
            {"id": 10, "name": "wav_nodocling", "effective": False, "status": "indexed"},
        ],
        "/pipelines/9/artifacts": {"document_id": 5, "chunks": [], "tables": []},
    })
    rc = cli_main.main(["get-doc", "5", "--pipeline", "wav_docling", "--json"])
    assert rc == 0
    # it fetched the NAMED pipeline's artifacts (id 9), not the effective one (10)
    assert any("/pipelines/9/artifacts" in c[1] for c in fh.calls)


def test_get_doc_no_effective_errors(fake_http, capsys):
    fake_http({"/documents/7/pipelines": [
        {"id": 1, "name": "x_docling", "effective": False, "status": "building"}]})
    rc = cli_main.main(["get-doc", "7", "--json"])
    assert rc == 1
    assert "no effective pipeline" in capsys.readouterr().err


def test_get_doc_unknown_named_pipeline_errors(fake_http, capsys):
    fake_http({"/documents/7/pipelines": [
        {"id": 1, "name": "x_docling", "effective": True, "status": "indexed"}]})
    rc = cli_main.main(["get-doc", "7", "--pipeline", "ghost", "--json"])
    assert rc == 1
    assert "no pipeline named" in capsys.readouterr().err


def test_search_doc_scopes_by_document_id(fake_http, capsys):
    fh = fake_http({"/query": {"hits": [_hit(i) for i in range(10)]}})
    rc = cli_main.main(["search-doc", "3", "sensor failure", "--top-k", "3", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["hits"]) == 3
    method, url, body = fh.calls[0]
    assert method == "POST" and url.endswith("/query")
    assert body == {"document_id": 3, "prompt": "sensor failure"}  # scoped by id, no corpus


def test_search_doc_pipeline_passthrough(fake_http):
    fh = fake_http({"/query": {"hits": []}})
    cli_main.main(["search-doc", "3", "q", "--pipeline", "afti_nodocling", "--json"])
    _, _, body = fh.calls[0]
    assert body["pipelines"] == ["afti_nodocling"]


def test_list_pipelines_by_document_json(fake_http, capsys):
    fake_http({"/documents/5/pipelines": [
        {"id": 9, "name": "wav_docling", "rating": 0.8, "status": "indexed",
         "effective": True}]})
    rc = cli_main.main(["list-pipelines", "--document-id", "5", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["document_id"] == 5
    assert out["pipelines"][0]["name"] == "wav_docling"


def test_list_pipelines_by_corpus_json(fake_http, capsys):
    fake_http({"/corpora/aero/pipelines": [
        {"name": "afti_docling", "document_id": 3, "rating": 0.9, "status": "indexed",
         "effective": True}]})
    rc = cli_main.main(["list-pipelines", "--corpus", "aero", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["corpus"] == "aero"
    assert out["pipelines"][0]["name"] == "afti_docling"


def test_list_pipelines_requires_exactly_one_scope(fake_http, capsys):
    fake_http({})
    rc = cli_main.main(["list-pipelines", "--json"])
    assert rc == 1
    assert "exactly one" in capsys.readouterr().err


def test_manifest_shape_and_invariants():
    from madosho_cli.manifest import build_manifest

    m = build_manifest()
    assert [t["name"] for t in m["tools"]] == [
        "search", "search-doc", "get-doc",
        "list-corpora", "list-documents", "list-pipelines",
        "create-corpus", "upload-document", "build-pipeline",
        "add-document-to-corpus", "document-status",
    ]
    for t in m["tools"]:
        assert set(t) >= {"name", "description", "parameters", "invocation"}
        assert t["description"].strip()
        params = t["parameters"]
        assert params["type"] == "object"
        props = params["properties"]
        inv = t["invocation"]
        assert inv["subcommand"] == t["name"]
        for p in inv["positional"] + inv["options"]:
            assert p in props, f"{t['name']}: {p} not in parameters"
        # required args must be positional, so the agent can't omit them
        assert set(params["required"]) <= set(inv["positional"])


def test_manifest_search_params():
    from madosho_cli.manifest import build_manifest

    search = next(t for t in build_manifest()["tools"] if t["name"] == "search")
    assert search["parameters"]["required"] == ["corpus", "query"]
    assert set(search["parameters"]["properties"]) == {
        "corpus", "query", "top_k", "pipeline"
    }
    assert search["invocation"] == {
        "subcommand": "search",
        "positional": ["corpus", "query"],
        "options": ["top_k", "pipeline"],
    }


def test_manifest_search_doc_params():
    from madosho_cli.manifest import build_manifest

    t = next(t for t in build_manifest()["tools"] if t["name"] == "search-doc")
    assert t["parameters"]["required"] == ["document_id", "query"]
    assert set(t["parameters"]["properties"]) == {
        "document_id", "query", "top_k", "pipeline"
    }
    assert t["invocation"] == {
        "subcommand": "search-doc",
        "positional": ["document_id", "query"],
        "options": ["top_k", "pipeline"],
    }


def test_manifest_list_pipelines_params():
    from madosho_cli.manifest import build_manifest

    t = next(t for t in build_manifest()["tools"] if t["name"] == "list-pipelines")
    # exactly-one-of corpus/document_id is enforced at runtime, so neither is
    # schema-required; both are options (no positional).
    assert t["parameters"]["required"] == []
    assert set(t["parameters"]["properties"]) == {"corpus", "document_id"}
    assert t["invocation"] == {
        "subcommand": "list-pipelines",
        "positional": [],
        "options": ["corpus", "document_id"],
    }


def test_agent_tools_cli_json(capsys):
    rc = cli_main.main(["agent-tools", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "tools" in out and len(out["tools"]) == 11


def test_agent_tools_cli_human(capsys):
    rc = cli_main.main(["agent-tools"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "search" in out and "get-doc" in out


# ---------------------------------------------------------------------------
# list-runs and cancel-run
# ---------------------------------------------------------------------------

def test_list_runs_active_filter_json(fake_http, capsys):
    """list-runs <cid> --active --json returns only pending/running rows."""
    fake_http({
        "/corpora/7/research": [
            {"id": 1, "status": "pending", "corpus_id": 7},
            {"id": 2, "status": "running", "corpus_id": 7},
            {"id": 3, "status": "completed", "corpus_id": 7},
            {"id": 4, "status": "failed", "corpus_id": 7},
        ],
    })
    rc = cli_main.main(["list-runs", "7", "--active", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    statuses = [r["status"] for r in out["runs"]]
    assert statuses == ["pending", "running"]


def test_cancel_run_yes_posts_and_prints_status(fake_http, capsys):
    """cancel-run <id> --yes POSTs to /research/{id}/cancel and prints the new status."""
    fh = fake_http({"/research/5/cancel": {"status": "cancelled"}})
    rc = cli_main.main(["cancel-run", "5", "--yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cancelled" in out
    post_calls = [(m, u) for m, u, _ in fh.calls if m == "POST"]
    assert any("/research/5/cancel" in u for _, u in post_calls)


def test_cancel_run_without_yes_stdin_n_aborts(fake_http, monkeypatch, capsys):
    """cancel-run without --yes and stdin 'n' aborts without hitting the endpoint."""
    fh = fake_http({"/research/5/cancel": {"status": "cancelled"}})
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = cli_main.main(["cancel-run", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aborted" in out
    # no POST should have been made
    assert not any("/cancel" in c[1] for c in fh.calls)
