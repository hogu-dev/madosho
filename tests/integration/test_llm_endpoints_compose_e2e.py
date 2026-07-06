# tests/integration/test_llm_endpoints_compose_e2e.py
"""Opt-in live smoke for the LLM endpoint registry against a running compose stack.

This test does NOT bring anything up. Run with:

    docker compose up -d            # stack must be running
    # Set MADOSHO_INDEX_LLM_* in your .env so the seeded default exists.
    # Example: MADOSHO_INDEX_LLM_PROVIDER=openai MADOSHO_INDEX_LLM_MODEL=gemma-4-e4b
    .venv/bin/python -m pytest tests/integration/test_llm_endpoints_compose_e2e.py -m slow -v

The test asserts that the env-seeded default LLM endpoint carries BOTH text and vision
capability and that at least one row is the vision default. This validates that the
contextual chunker, eval, Scrying answer, AND the extraction comparison all share one
multimodal endpoint without a second server.

Dev override: compose.override.yaml remaps the control plane to host :8002, so on a
dev setup run with:

    MADOSHO_CONTROL_URL=http://localhost:8002 .venv/bin/python -m pytest \
        tests/integration/test_llm_endpoints_compose_e2e.py -m slow -v
"""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

pytestmark = pytest.mark.slow

CONTROL = os.environ.get("MADOSHO_CONTROL_URL", "http://localhost:8000")


def _stack_up() -> bool:
    try:
        urllib.request.urlopen(f"{CONTROL}/corpora", timeout=2)
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_stack():
    if not _stack_up():
        pytest.skip(
            f"compose stack not reachable at {CONTROL} - start it (docker compose up -d)"
        )


def test_seeded_endpoint_has_text_and_vision():
    with urllib.request.urlopen(f"{CONTROL}/llm-endpoints", timeout=10) as resp:
        rows = json.loads(resp.read())

    assert rows, "expected at least one LLM endpoint (env-seeded default)"

    defaults = [r for r in rows if r["is_default"]]
    assert defaults, "expected exactly one row with is_default=True"
    default = defaults[0]

    assert default["supports_text"] is True, (
        f"default endpoint {default.get('name')!r} does not support text"
    )
    assert default["supports_vision"] is True, (
        f"default endpoint {default.get('name')!r} does not support vision - "
        "seed it via MADOSHO_INDEX_LLM_* in your .env (first-boot seeding sets both)"
    )

    assert any(r["is_vision_default"] for r in rows), (
        "no row has is_vision_default=True - env-seeded endpoint should carry this flag"
    )
