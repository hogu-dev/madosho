"""Accounting wrapper around any LlmClient.

WHY a wrapper instead of teaching the loop to count: the loop stays
accounting-blind (research lane frozen), and any client - real or test
fake - gets metered identically. The wrapper satisfies the same LlmClient
protocol, so the loop cannot tell it is being counted.

max_calls is a hard BACKSTOP, not the primary cap: the orchestrator sizes
the round budget so a well-behaved run finishes UNDER the cap and still
ends with a draft (loop.py spends one call per round plus one forced
synthesis). Raising here means the loop's call pattern changed - and the
cap must still hold, because a rate-limited upstream locks the user out.
"""
from __future__ import annotations

from research_agent.types import AssistantTurn

from .types import Usage


class CallCapExceeded(RuntimeError):
    """A run tried to spend more LLM calls than its max_llm_calls cap."""


class CountingLlm:
    def __init__(self, inner, max_calls: int | None = None):
        self.inner = inner
        self.max_calls = max_calls
        self.usage = Usage()

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        if self.max_calls is not None and self.usage.llm_calls >= self.max_calls:
            raise CallCapExceeded(f"llm call cap reached ({self.max_calls})")
        turn = self.inner.complete(messages, tools)
        self.usage.llm_calls += 1
        u = turn.usage or {}
        self.usage.prompt_tokens += int(u.get("prompt_tokens") or 0)
        self.usage.completion_tokens += int(u.get("completion_tokens") or 0)
        self.usage.total_tokens += int(u.get("total_tokens") or 0)
        return turn
