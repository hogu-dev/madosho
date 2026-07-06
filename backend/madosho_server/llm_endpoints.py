from __future__ import annotations

import base64
import dataclasses
import os
from typing import Callable

from sqlalchemy import select

from madosho_server import db
from madosho_server.llm import complete, respond


def endpoint_creds(settings, row):
    """Return a Settings COPY bound to this endpoint's OWN api_base + key
    (key read from os.environ[key_env_var] at call time, never stored). Frozen
    settings are not mutated."""
    key = os.environ.get(row.key_env_var) if row.key_env_var else None
    return dataclasses.replace(settings, llm_api_base=row.api_base, llm_api_key=key)


def resolve_llm(session, settings, endpoint: "db.LlmEndpoint | None" = None):
    """Return (callable, row). `callable(prompt) -> str` is bound to the
    endpoint's OWN api_base/key (a replace() copy of the frozen Settings), so
    different endpoints can point at different servers. endpoint=None picks the
    default row. Returns (None, None) when nothing resolves."""
    row = endpoint or session.scalar(
        select(db.LlmEndpoint).where(db.LlmEndpoint.is_default.is_(True)))
    if row is None:
        return None, None
    # Capture into locals so the closure is safe after the session closes.
    provider, model, flavor = row.provider, row.model, row.api_flavor
    creds = endpoint_creds(settings, row)

    def _call(prompt: str) -> str:
        if flavor == "responses":
            # Responses-API servers take the bare prompt as input_data.
            return respond(prompt, provider=provider, model=model, settings=creds)
        resp = complete(messages=[{"role": "user", "content": prompt}],
                        provider=provider, model=model, settings=creds)
        return resp.choices[0].message.content

    return _call, row


def resolve_vision_endpoint(session, settings):
    """Return (provider, model, bound_settings, api_flavor) for the default VISION
    endpoint, or None when no vision-capable default exists. bound_settings carries
    the endpoint's OWN api_base/key via endpoint_creds(), so the vision lane can hit
    a different server than the text default."""
    row = session.scalar(
        select(db.LlmEndpoint).where(db.LlmEndpoint.is_vision_default.is_(True)))
    if row is None:
        return None
    return row.provider, row.model, endpoint_creds(settings, row), row.api_flavor


def resolve_vision_client(session, settings, endpoint: "db.LlmEndpoint | None" = None):
    """Return (callable, row) for a VISION endpoint, mirroring resolve_llm but for
    the multimodal kernel seam. `callable(prompt, images) -> str` base64-encodes the
    PNG bytes into provider image_url messages (the wire format the kernel's
    VisionClient deliberately does not know about). endpoint=None picks the
    is_vision_default row. Returns (None, None) when no vision endpoint resolves ->
    the vision parser then raises ConfigError, surfacing the missing endpoint."""
    row = endpoint or session.scalar(
        select(db.LlmEndpoint).where(db.LlmEndpoint.is_vision_default.is_(True)))
    if row is None:
        return None, None
    # Capture into locals so the closure is safe after the session closes.
    provider, model, flavor = row.provider, row.model, row.api_flavor
    creds = endpoint_creds(settings, row)

    def _call(prompt: str, images: list[bytes]) -> str:
        if flavor == "responses":
            # Responses-API multimodal shape: input_text/input_image parts
            # (`detail` is required by the strict param schema).
            parts: list[dict] = [{"type": "input_text", "text": prompt}]
            for png in images:
                b64 = base64.b64encode(png).decode("ascii")
                parts.append({"type": "input_image", "detail": "auto",
                              "image_url": f"data:image/png;base64,{b64}"})
            return respond([{"role": "user", "content": parts}],
                           provider=provider, model=model, settings=creds)
        content: list[dict] = [{"type": "text", "text": prompt}]
        for png in images:
            b64 = base64.b64encode(png).decode("ascii")
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        resp = complete(messages=[{"role": "user", "content": content}],
                        provider=provider, model=model, settings=creds)
        return resp.choices[0].message.content or ""

    return _call, row
