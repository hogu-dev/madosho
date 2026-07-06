# tests/integration/test_research_agent_compose_e2e.py
"""Opt-in live smoke for the research agent against a running compose stack + a real
LLM. Like test_research_cli_compose_e2e.py, it does not bring anything up. Run with:

    docker compose up -d            # stack must be seeded (e.g. the aerospace corpus)
    export RESEARCH_AGENT_PROVIDER=... RESEARCH_AGENT_MODEL=...
    # (and RESEARCH_AGENT_API_BASE / RESEARCH_AGENT_API_KEY as needed)
    .venv/bin/python -m pytest tests/integration/test_research_agent_compose_e2e.py -m slow -v
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

import research_agent
from research_agent.types import LlmEndpoint, RunBudget

pytestmark = pytest.mark.slow

CONTROL = os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000")
CORPUS = os.environ.get("RESEARCH_AGENT_E2E_CORPUS", "aerospace")


def _stack_up() -> bool:
    # Any HTTP response (including a 401 when auth is on) means the stack is up; only
    # a connection failure means it is not. The old probe read the auth-on 401 as
    # "stack down" and skipped the suite under the shipped default.
    try:
        urllib.request.urlopen(f"{CONTROL}/health", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_stack_and_provider():
    if not _stack_up():
        pytest.skip("compose stack not reachable - start it (docker compose up -d)")
    if not os.environ.get("MADOSHO_API_KEY"):
        pytest.skip(
            "set MADOSHO_API_KEY - the agent drives madosho-cli, which authenticates "
            "via a bearer key, not the admin session cookie"
        )
    if not os.environ.get("RESEARCH_AGENT_PROVIDER") or not os.environ.get("RESEARCH_AGENT_MODEL"):
        pytest.skip("set RESEARCH_AGENT_PROVIDER and RESEARCH_AGENT_MODEL to run this")


def test_research_run_produces_cited_report():
    llm = research_agent.AnyLlmClient(LlmEndpoint(
        provider=os.environ["RESEARCH_AGENT_PROVIDER"],
        model=os.environ["RESEARCH_AGENT_MODEL"],
        api_key=os.environ.get("RESEARCH_AGENT_API_KEY"),
        api_base=os.environ.get("RESEARCH_AGENT_API_BASE"),
    ))
    report = research_agent.run(
        f"Using the {CORPUS} corpus, summarize what the documents say about flight "
        "control sensor handling, with citations.",
        tools=research_agent.CliToolProvider(["madosho-cli"]),
        llm=llm,
        budget=RunBudget(max_context_chars=40_000, max_rounds=4),
    )
    assert report.markdown.strip(), "expected a non-empty report"
    assert report.stop_reason in {"final", "round_cap"}
    # the agent actually called a tool and gathered at least one citation
    assert any(e["kind"] == "tool_call" for e in report.run_log)
    assert len(report.citations) >= 1
