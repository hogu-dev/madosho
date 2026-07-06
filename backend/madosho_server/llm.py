from __future__ import annotations

from typing import Any

from any_llm import completion       # patched in tests via madosho_server.llm.completion
from any_llm import responses        # patched in tests via madosho_server.llm.responses

from madosho_server.settings import Settings


class ProviderNotConfigured(Exception):
    """Raised when a generation request names no provider/model."""


def _creds(settings: Settings) -> dict[str, str]:
    creds: dict[str, str] = {}
    if settings.llm_api_key:
        creds["api_key"] = settings.llm_api_key
    if settings.llm_api_base:
        creds["api_base"] = settings.llm_api_base
    return creds


def complete(messages: list[dict], provider: str, model: str,
             settings: Settings, stream: bool = False) -> Any:
    """Call the configured provider via any-llm. Returns an OpenAI-shaped
    completion object (stream=False) or an iterator of chunks (stream=True)."""
    if not provider or not model:
        raise ProviderNotConfigured("no LLM provider/model specified for this request")
    return completion(model=model, provider=provider, messages=messages,
                      stream=stream, **_creds(settings))


def respond(input_data: Any, provider: str, model: str, settings: Settings) -> str:
    """Call a Responses-API endpoint via any-llm and return the output text.

    Always streams and joins the output_text deltas rather than reading the
    non-streaming `output` array: at least one Responses-API proxy in the wild
    completes non-streaming requests with an EMPTY output array while billing
    the tokens, and real OpenAI streams fine -- so streaming is the one path
    that works everywhere. A bare-string prompt is wrapped into the
    message-list form for the same reason: real OpenAI accepts a string, but
    such proxies can 400 on it ("Input must be a list")."""
    if not provider or not model:
        raise ProviderNotConfigured("no LLM provider/model specified for this request")
    if isinstance(input_data, str):
        input_data = [{"role": "user",
                       "content": [{"type": "input_text", "text": input_data}]}]
    events = responses(model=model, provider=provider, input_data=input_data,
                       stream=True, **_creds(settings))
    parts: list[str] = []
    for ev in events:
        if getattr(ev, "type", None) == "response.output_text.delta":
            parts.append(ev.delta)
    return "".join(parts)
