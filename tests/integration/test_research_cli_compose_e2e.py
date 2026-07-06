"""Opt-in live smoke for the madosho CLI against a running compose stack.

Assumes the stack is already up and seeded (like test_pipelines_compose_e2e.py); it does
not bring anything up itself. Run with:

    docker compose up -d
    .venv/bin/python -m pytest tests/integration/test_research_cli_compose_e2e.py -m slow -v
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from madosho_cli import main as cli_main

pytestmark = pytest.mark.slow

CONTROL = os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000")


def _stack_up() -> bool:
    # Any HTTP response (including 401 when auth is on) means the stack is up; only a
    # connection failure means it is not. The old probe hit /corpora unauthenticated
    # and wrongly read the 401 as "stack down", skipping the suite under the shipped
    # auth-on default.
    try:
        urllib.request.urlopen(f"{CONTROL}/health", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_stack():
    if not _stack_up():
        pytest.skip("compose stack not reachable - start it (docker compose up -d)")
    if not os.environ.get("MADOSHO_API_KEY"):
        pytest.skip(
            "set MADOSHO_API_KEY - the CLI authenticates via a bearer key, not the "
            "admin session cookie (mint one with madosho-keys create)"
        )


def test_list_corpora_live(capsys):
    rc = cli_main.main(["list-corpora", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "corpora" in out
    assert any(c["name"] == "aerospace" for c in out["corpora"])


def test_search_live(capsys):
    rc = cli_main.main(["search", "aerospace", "flight control", "--top-k", "3", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out["hits"], list)
    assert len(out["hits"]) <= 3


def test_agent_tools_live(capsys):
    rc = cli_main.main(["agent-tools", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [t["name"] for t in out["tools"]] == [
        "search", "search-doc", "get-doc",
        "list-corpora", "list-documents", "list-pipelines"
    ]
