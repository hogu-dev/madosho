"""LLM client seam.

LlmClient is what the loop calls; AnyLlmClient is the one concrete client, wrapping
any_llm so any OpenAI-compatible provider works (pluggable, no default model). The
loop and its tests never touch any_llm directly - tests inject a scripted client.

The `from any_llm import completion` seam matches madosho_server/llm.py: tests
monkeypatch research_agent.llm.completion.
"""
from __future__ import annotations

import json
from typing import Protocol

from any_llm import completion   # patched in tests via research_agent.llm.completion

from .types import AssistantTurn, LlmEndpoint, ToolCall


class LlmClient(Protocol):
    """One model turn: given the running messages and the tool schemas, return a
    normalized AssistantTurn (prose and/or tool calls)."""

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        ...


class AnyLlmClient:
    """Concrete LlmClient backed by any_llm. Normalizes the OpenAI-shaped response
    into AssistantTurn so the loop stays client-agnostic."""

    def __init__(self, endpoint: LlmEndpoint):
        self.endpoint = endpoint

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        creds: dict = {}
        if self.endpoint.api_key:
            creds["api_key"] = self.endpoint.api_key
        if self.endpoint.api_base:
            creds["api_base"] = self.endpoint.api_base
        resp = completion(
            model=self.endpoint.model,
            provider=self.endpoint.provider,
            messages=messages,
            tools=(tools or None),
            tool_choice=("auto" if tools else None),
            stream=False,
            **creds,
        )
        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            fn = tc.function
            try:
                parsed = json.loads(fn.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            calls.append(ToolCall(id=tc.id, name=fn.name, arguments=parsed))
        return AssistantTurn(text=getattr(msg, "content", None), tool_calls=calls)
