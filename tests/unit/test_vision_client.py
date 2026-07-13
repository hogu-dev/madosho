"""Service-side wiring for the vision parser: the (prompt, images)->str client
that resolve_vision_client builds, and the recipe reader tasks uses to pick the
endpoint. Mirrors test_llm_endpoints / test_chunker_options_endpoints."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from madosho_server import db, llm_endpoints, tasks
from madosho_server.settings import Settings

BASE = Settings(database_url="sqlite://", qdrant_url="", filestore_dir="",
                corpora_dir="")


@pytest.fixture
def session(tmp_path):
    db.configure_engine(f"sqlite:///{tmp_path/'v.db'}")
    db.create_all()
    with db.SessionLocal() as s:
        yield s


def test_resolve_vision_client_none_when_no_vision_default(session):
    call, row = llm_endpoints.resolve_vision_client(session, BASE)
    assert call is None and row is None


def test_resolve_vision_client_builds_image_messages(session, monkeypatch):
    monkeypatch.setenv("VIS_KEY", "secret-vis")
    session.add(db.LlmEndpoint(name="vgpu", provider="openai", model="gemma-vision",
                               api_base="http://h:9000/v1", key_env_var="VIS_KEY",
                               supports_vision=True, is_vision_default=True))
    session.commit()

    captured = {}
    def fake_complete(messages, provider, model, settings, stream=False,
                      reasoning_effort=None):
        captured.update(messages=messages, provider=provider, model=model,
                        api_base=settings.llm_api_base, api_key=settings.llm_api_key)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="PAGE TEXT"))])
    monkeypatch.setattr(llm_endpoints, "complete", fake_complete)

    call, row = llm_endpoints.resolve_vision_client(session, BASE)
    assert row.name == "vgpu"
    out = call("transcribe this", [b"\x89PNG-one", b"\x89PNG-two"])
    assert out == "PAGE TEXT"
    assert captured["provider"] == "openai" and captured["model"] == "gemma-vision"
    assert captured["api_base"] == "http://h:9000/v1"
    assert captured["api_key"] == "secret-vis"
    # one user message: a text part followed by one image_url part per image
    content = captured["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "transcribe this"}
    image_parts = [p for p in content if p["type"] == "image_url"]
    assert len(image_parts) == 2
    assert all(p["image_url"]["url"].startswith("data:image/png;base64,")
               for p in image_parts)


def test_resolve_vision_client_responses_flavor_builds_input_parts(session, monkeypatch):
    session.add(db.LlmEndpoint(name="codex", provider="openai", model="gpt-5.5",
                               api_base="http://proxy:10531/v1",
                               supports_vision=True, is_vision_default=True,
                               api_flavor="responses"))
    session.commit()

    captured = {}
    def fake_respond(input_data, provider, model, settings, reasoning_effort=None):
        captured.update(input_data=input_data, provider=provider, model=model,
                        api_base=settings.llm_api_base)
        return "TRANSCRIPT"
    monkeypatch.setattr(llm_endpoints, "respond", fake_respond)
    monkeypatch.setattr(llm_endpoints, "complete",
                        lambda *a, **k: pytest.fail("chat path used for responses flavor"))

    call, row = llm_endpoints.resolve_vision_client(session, BASE)
    assert call("transcribe this", [b"\x89PNG-one", b"\x89PNG-two"]) == "TRANSCRIPT"
    assert captured["provider"] == "openai" and captured["model"] == "gpt-5.5"
    assert captured["api_base"] == "http://proxy:10531/v1"
    # Responses wire shape: input_text part then one input_image per image,
    # each with the REQUIRED detail field and a data: URI (no URL hosting).
    parts = captured["input_data"][0]["content"]
    assert parts[0] == {"type": "input_text", "text": "transcribe this"}
    image_parts = [p for p in parts if p["type"] == "input_image"]
    assert len(image_parts) == 2
    assert all(p["detail"] == "auto" for p in image_parts)
    assert all(p["image_url"].startswith("data:image/png;base64,") for p in image_parts)


def test_resolve_vision_client_explicit_endpoint_overrides_default(session, monkeypatch):
    session.add_all([
        db.LlmEndpoint(name="vdef", provider="o", model="m", api_base="u",
                       supports_vision=True, is_vision_default=True),
        db.LlmEndpoint(name="vpick", provider="o", model="picked", api_base="u",
                       supports_vision=True, is_vision_default=False),
    ])
    session.commit()
    picked = session.query(db.LlmEndpoint).filter_by(name="vpick").one()
    _, row = llm_endpoints.resolve_vision_client(session, BASE, picked)
    assert row.name == "vpick"


def test_parser_vision_endpoint_reads_mapping_form():
    cfg = {"ingest": {"parser": {"vision": {"vision_endpoint": "vgpu"}}}}
    assert tasks._parser_vision_endpoint(cfg) == "vgpu"


def test_parser_vision_endpoint_none_for_bare_name():
    cfg = {"ingest": {"parser": "vision"}}
    assert tasks._parser_vision_endpoint(cfg) is None


def test_parser_vision_endpoint_none_for_non_vision_parser():
    cfg = {"ingest": {"parser": {"docling": {}}}}
    assert tasks._parser_vision_endpoint(cfg) is None


def test_recipe_config_emits_vision_endpoint_option():
    base = {"corpus": "c", "ingest": {}, "query": []}
    cfg = tasks.recipe_config(base, parser="vision", chunker="recursive-text",
                              embedder="hash-embedder",
                              options={"parser": {"vision_endpoint": "vgpu"}})
    assert cfg["ingest"]["parser"] == {"vision": {"vision_endpoint": "vgpu"}}
