"""The madosho MCP server: manifest-driven tool list + core-backed dispatch."""
from __future__ import annotations

import argparse
import asyncio
import contextlib

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server

from madosho_cli import core, http, manifest


def _extract_bearer(scope: dict) -> str | None:
    """Return the bearer token from an ASGI scope's headers list, or None.

    ASGI header names arrive as lowercase bytes per the spec, so we match
    b"authorization" directly. The scheme prefix ("Bearer ") is compared
    case-insensitively as the HTTP spec allows any casing.
    Returns the raw token without the "Bearer " prefix, or None when the
    header is absent or uses a non-bearer scheme (Basic, Digest, etc.).
    """
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            decoded = value.decode("latin-1")
            if decoded[:7].lower() == "bearer ":
                return decoded[7:]
    return None


def build_tools() -> list[types.Tool]:
    """One MCP Tool per agent-tools manifest entry. inputSchema IS the manifest
    `parameters`, so the manifest stays the single source of truth (no drift)."""
    return [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["parameters"],
        )
        for t in manifest.build_manifest()["tools"]
    ]


def dispatch(name: str, arguments: dict) -> dict:
    """Route an MCP tool call to madosho_cli.core and return its dict result.
    Unknown name -> ValueError; core's CliError propagates (the SDK turns either
    into an isError tool result for the calling model)."""
    if name == "search":
        return core.search(
            arguments["corpus"], arguments["query"],
            top_k=arguments.get("top_k", 8), pipeline=arguments.get("pipeline"))
    if name == "search-doc":
        return core.search_document(
            arguments["document_id"], arguments["query"],
            top_k=arguments.get("top_k", 8), pipeline=arguments.get("pipeline"))
    if name == "get-doc":
        return core.get_doc(arguments["document_id"], pipeline=arguments.get("pipeline"))
    if name == "list-corpora":
        return core.list_corpora()
    if name == "list-documents":
        return core.list_documents(arguments["corpus"])
    if name == "list-pipelines":
        return core.list_pipelines(
            corpus=arguments.get("corpus"), document_id=arguments.get("document_id"))
    if name == "create-corpus":
        return core.create_corpus(arguments["name"])
    if name == "upload-document":
        return core.upload_document(
            path=arguments.get("path"),
            content_b64=arguments.get("content_b64"),
            filename=arguments.get("filename"),
            corpus=arguments.get("corpus"),
            parser=arguments.get("parser"),
            chunker=arguments.get("chunker"),
            embedder=arguments.get("embedder"),
            options=arguments.get("options"),
        )
    if name == "build-pipeline":
        return core.build_pipeline(
            arguments["document_id"],
            arguments["name"],
            parser=arguments.get("parser"),
            chunker=arguments.get("chunker"),
            embedder=arguments.get("embedder"),
            options=arguments.get("options"),
            config=arguments.get("config"),
        )
    if name == "add-document-to-corpus":
        return core.add_document_to_corpus(
            arguments["corpus"],
            arguments["document_id"],
        )
    if name == "document-status":
        return core.document_status(arguments["document_id"])
    raise ValueError(f"unknown tool: {name!r}")


SERVER_NAME = "madosho"
SERVER_VERSION = "1"


async def _list_tools() -> list[types.Tool]:
    return build_tools()


async def _call_tool(name: str, arguments: dict) -> dict:
    # Returning a dict: the SDK puts it in structuredContent + a JSON TextContent.
    # Raising (unknown tool -> ValueError, HTTP failure -> CliError): the SDK returns
    # an isError result carrying the message - the model reads it and routes around it.
    return dispatch(name, arguments)


def build_server() -> Server:
    """A low-level MCP Server with the manifest tools wired to core."""
    server = Server(SERVER_NAME, version=SERVER_VERSION)
    server.list_tools()(_list_tools)
    server.call_tool()(_call_tool)
    return server


def serve_stdio(server: Server) -> None:
    """Serve over stdio (an MCP host spawns this process and speaks JSON-RPC)."""
    async def _main() -> None:
        async with mcp.server.stdio.stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_main())


def build_http_app(server: Server):
    """Build a Starlette app serving the MCP server over streamable-HTTP at /mcp."""
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    session_manager = StreamableHTTPSessionManager(
        app=server, stateless=True, json_response=True)

    async def handle(scope, receive, send):
        # WHY this is safe for concurrent requests:
        # Each incoming HTTP connection is dispatched in its own asyncio task by
        # uvicorn / the streamable-HTTP session manager. asyncio gives each new
        # task a copy of the contextvar namespace, so setting the contextvar here
        # only affects THIS task's copy. In-flight requests in other tasks are
        # invisible to each other: no locking needed.
        # The finally-reset restores whatever value the contextvar held before
        # this call (normally None), so if a task is ever reused a stale token
        # cannot bleed into the next request.
        token = _extract_bearer(scope)
        tok = http.set_request_token(token)
        try:
            await session_manager.handle_request(scope, receive, send)
        finally:
            http.reset_request_token(tok)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    return Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan)


def serve_http(server: Server, host: str, port: int) -> None:
    """Serve over streamable-HTTP (for hosts that connect to MCP servers by URL)."""
    import uvicorn

    uvicorn.run(build_http_app(server), host=host, port=port)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="madosho-mcp",
        description="madosho retrieval tools as an MCP server (retrieval only). Default "
                    "transport is stdio; --http serves streamable-HTTP on a port.")
    ap.add_argument("--http", action="store_true",
                    help="serve streamable-HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1",
                    help="--http bind host (default 127.0.0.1; use 0.0.0.0 to expose "
                         "to other hosts -- safe because each caller's bearer is "
                         "forwarded and enforced upstream)")
    ap.add_argument("--port", type=int, default=8089, help="--http bind port")
    args = ap.parse_args(argv)
    server = build_server()
    if args.http:
        serve_http(server, args.host, args.port)
    else:
        serve_stdio(server)
    return 0
