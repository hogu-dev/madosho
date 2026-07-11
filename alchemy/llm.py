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

Stage E: complete() is threadsafe. Parallel section units share ONE
CountingLlm per run, so the cap check and the spend must be atomic - the
old check-then-increment let two threads both pass with one slot left and
overspend the cap. See complete() for the reservation pattern.
"""
from __future__ import annotations

import threading
from dataclasses import replace

from research_agent.types import AssistantTurn

from .types import Usage


class CallCapExceeded(RuntimeError):
    """A run tried to spend more LLM calls than its max_llm_calls cap."""


class CountingLlm:
    def __init__(self, inner, max_calls: int | None = None):
        self.inner = inner
        self.max_calls = max_calls
        self.usage = Usage()
        self._lock = threading.Lock()

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        # RESERVE a slot under the lock, then call the provider OUTSIDE it.
        # WHY not hold the lock across inner.complete(): that would serialize
        # every LLM call and defeat concurrent units entirely. WHY not
        # check-without-reserving (the old shape): two threads can both pass
        # the check with one slot left and overspend the cap (TOCTOU).
        # Reserving first makes check+spend atomic while the calls themselves
        # still run concurrently; a provider failure RELEASES the slot,
        # preserving the observable rule that only calls actually made are
        # counted (test_failed_provider_call_releases_its_slot relies on it).
        with self._lock:
            if self.max_calls is not None and self.usage.llm_calls >= self.max_calls:
                raise CallCapExceeded(f"llm call cap reached ({self.max_calls})")
            self.usage.llm_calls += 1
        try:
            turn = self.inner.complete(messages, tools)
        except BaseException:
            with self._lock:
                self.usage.llm_calls -= 1
            raise
        u = turn.usage or {}
        with self._lock:
            self.usage.prompt_tokens += int(u.get("prompt_tokens") or 0)
            self.usage.completion_tokens += int(u.get("completion_tokens") or 0)
            self.usage.total_tokens += int(u.get("total_tokens") or 0)
        return turn

    def snapshot(self) -> Usage:
        """A consistent copy of the counters for cross-thread reads (the
        parallel path's quota math). Reading self.usage directly mid-run can
        tear ACROSS fields while another thread sits between increments."""
        with self._lock:
            return replace(self.usage)
