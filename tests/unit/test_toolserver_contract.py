"""Guard: the tool server's generated OpenAPI must match the agent-tools manifest
exactly - so the CLI, the tool server, and (later) the MCP server cannot drift.
The manifest is the single source of truth for tool schemas."""
from __future__ import annotations

from fastapi.testclient import TestClient

from madosho_cli.manifest import build_manifest
from madosho_toolserver.app import app


def _op_to_request_schema(spec: dict) -> dict[str, dict]:
    """operationId -> resolved request-body JSON schema, for each POST path."""
    out = {}
    for _path, item in spec["paths"].items():
        post = item.get("post")
        if not post:
            continue
        op = post["operationId"]
        ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        name = ref.split("/")[-1]
        out[op] = spec["components"]["schemas"][name]
    return out


def test_openapi_publishes_exactly_the_manifest_tools():
    spec = TestClient(app).get("/openapi.json").json()
    op_schemas = _op_to_request_schema(spec)
    manifest_names = {t["name"] for t in build_manifest()["tools"]}
    # exactly the manifest tools are exposed as operations (no more, no fewer)
    assert set(op_schemas) == manifest_names


def test_each_tool_request_schema_matches_manifest_parameters():
    spec = TestClient(app).get("/openapi.json").json()
    op_schemas = _op_to_request_schema(spec)
    for tool in build_manifest()["tools"]:
        params = tool["parameters"]
        schema = op_schemas[tool["name"]]
        assert set(schema.get("properties", {})) == set(params["properties"]), tool["name"]
        assert set(schema.get("required", [])) == set(params.get("required", [])), tool["name"]


def test_operation_ids_are_valid_tool_names():
    # Open WebUI / OpenAI function names must match ^[a-zA-Z0-9_-]+$
    import re
    spec = TestClient(app).get("/openapi.json").json()
    for op in _op_to_request_schema(spec):
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", op), op
