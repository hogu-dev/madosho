"""The agent-tools manifest - the reuse contract (in place of MCP).

`madosho-cli agent-tools --json` emits this. A research agent's CliToolProvider
reads it to learn what this CLI offers: each entry's `parameters` is a
JSON Schema it can hand straight to an OpenAI-format tool-calling model, and
`invocation` tells the provider how to turn a tool call into an argv:

    <cli> <subcommand> <positional values...> [--<opt> <value> ...] --json

with option param names lower-cased and underscores turned into hyphens
(top_k -> --top-k). Required params are always positional, so a tool call cannot
omit them.

Keeping behaviour in a declared manifest (not hardcoded in the agent) is what
lets any application be driven by the same agent: ship a CLI that emits a
compatible manifest and accepts --json subcommands.
"""
from __future__ import annotations

from typing import Any

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search",
        "scope": "read",
        "description": (
            "RAG retrieval. Search a corpus for the chunks most relevant to a "
            "query and return them ranked, with citations. Use this to gather "
            "evidence before writing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "corpus": {"type": "string", "description": "corpus name to search"},
                "query": {"type": "string", "description": "the search query text"},
                "top_k": {
                    "type": "integer",
                    "description": "max number of chunks to return (default 8)",
                },
                "pipeline": {
                    "type": "string",
                    "description": (
                        "optional pipeline name to retrieve through (overrides "
                        "each document's effective pipeline)"
                    ),
                },
            },
            "required": ["corpus", "query"],
        },
        "invocation": {
            "subcommand": "search",
            "positional": ["corpus", "query"],
            "options": ["top_k", "pipeline"],
        },
    },
    {
        "name": "search-doc",
        "scope": "read",
        "description": (
            "RAG retrieval scoped to ONE document (by id), corpus-independent. "
            "Same ranked, cited chunks as `search`, but limited to a single "
            "document - including a loose document in no corpus. Use it to gather "
            "evidence from one document without pulling in a whole corpus."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "the document id (from list-documents) to search within",
                },
                "query": {"type": "string", "description": "the search query text"},
                "top_k": {
                    "type": "integer",
                    "description": "max number of chunks to return (default 8)",
                },
                "pipeline": {
                    "type": "string",
                    "description": (
                        "optional pipeline name to retrieve through (defaults to "
                        "the document's effective pipeline)"
                    ),
                },
            },
            "required": ["document_id", "query"],
        },
        "invocation": {
            "subcommand": "search-doc",
            "positional": ["document_id", "query"],
            "options": ["top_k", "pipeline"],
        },
    },
    {
        "name": "get-doc",
        "scope": "read",
        "description": (
            "Return the full extracted text of one document (every chunk, in "
            "order). This is NOT retrieval - it loads the whole document. Use "
            "`search` / `search-doc` to find relevant passages; use this when you "
            "need the entire document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "the document id (from list-documents)",
                },
                "pipeline": {
                    "type": "string",
                    "description": (
                        "optional pipeline name; defaults to the document's "
                        "effective pipeline"
                    ),
                },
            },
            "required": ["document_id"],
        },
        "invocation": {
            "subcommand": "get-doc",
            "positional": ["document_id"],
            "options": ["pipeline"],
        },
    },
    {
        "name": "list-corpora",
        "scope": "read",
        "description": "List the corpora available to search.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "invocation": {"subcommand": "list-corpora", "positional": [], "options": []},
    },
    {
        "name": "list-documents",
        "scope": "read",
        "description": (
            "List the documents in a corpus (id, filename, status). Use this to "
            "resolve which documents to target or read whole."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "corpus": {"type": "string", "description": "corpus name"},
            },
            "required": ["corpus"],
        },
        "invocation": {
            "subcommand": "list-documents",
            "positional": ["corpus"],
            "options": [],
        },
    },
    {
        "name": "list-pipelines",
        "scope": "read",
        "description": (
            "List the named pipelines (extraction/retrieval recipes) built for a "
            "document or across a corpus, with their ratings. Use this to discover "
            "the pipeline names you can pass to search / search-doc / get-doc via "
            "--pipeline. Give exactly one of corpus or document_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "corpus": {
                    "type": "string",
                    "description": "list pipelines across this corpus's documents",
                },
                "document_id": {
                    "type": "integer",
                    "description": "list pipelines built on this one document",
                },
            },
            "required": [],
        },
        "invocation": {
            "subcommand": "list-pipelines",
            "positional": [],
            "options": ["corpus", "document_id"],
        },
    },
    {
        "name": "create-corpus",
        "scope": "write",
        "description": (
            "Create a new corpus (document collection) by name. "
            "Returns the new corpus id and name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "corpus name to create"},
            },
            "required": ["name"],
        },
        "invocation": {
            "subcommand": "create-corpus",
            "positional": ["name"],
            "options": [],
        },
    },
    {
        "name": "upload-document",
        "scope": "write",
        "description": (
            "Upload a document to madosho. Provide either 'path' (a local file "
            "path) or 'content_b64' (base-64 encoded bytes) -- exactly one is "
            "required at call time (both present or neither is an error). "
            "'corpus' assigns the document to a corpus on upload. 'filename' sets "
            "the display name for base-64 uploads. 'parser', 'chunker', 'embedder', "
            "and 'options' override the default pipeline components. Returns the "
            "document id and status; indexing is asynchronous -- poll "
            "'document-status' to track progress."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "local file path to upload",
                },
                "content_b64": {
                    "type": "string",
                    "description": "base-64 encoded document bytes (alternative to path)",
                },
                "filename": {
                    "type": "string",
                    "description": "display filename (required when using content_b64)",
                },
                "corpus": {
                    "type": "string",
                    "description": "assign to this corpus by name on upload",
                },
                "parser": {
                    "type": "string",
                    "description": "parser component override",
                },
                "chunker": {
                    "type": "string",
                    "description": "chunker component override",
                },
                "embedder": {
                    "type": "string",
                    "description": "embedder component override",
                },
                "options": {
                    "type": "object",
                    "description": "additional pipeline component options",
                },
            },
            "required": [],
        },
        "invocation": {
            "subcommand": "upload-document",
            "positional": ["path"],
            "options": ["filename", "corpus", "parser", "chunker", "embedder", "options"],
        },
    },
    {
        "name": "build-pipeline",
        "scope": "write",
        "description": (
            "Build a named extraction/retrieval pipeline for an existing document. "
            "Extraction runs in the background (parsing + chunking + embedding). "
            "Poll 'document-status' to track progress. "
            "Optional 'parser', 'chunker', 'embedder', or 'options' override the "
            "defaults; a raw 'config' dict takes full precedence over component args."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "document id to build the pipeline for",
                },
                "name": {
                    "type": "string",
                    "description": "pipeline name (must be unique within the document)",
                },
                "parser": {
                    "type": "string",
                    "description": "parser component override",
                },
                "chunker": {
                    "type": "string",
                    "description": "chunker component override",
                },
                "embedder": {
                    "type": "string",
                    "description": "embedder component override",
                },
                "options": {
                    "type": "object",
                    "description": "additional component options",
                },
                "config": {
                    "type": "object",
                    "description": "raw pipeline config dict (overrides component-level args)",
                },
            },
            "required": ["document_id", "name"],
        },
        "invocation": {
            "subcommand": "build-pipeline",
            "positional": ["document_id", "name"],
            "options": ["parser", "chunker", "embedder", "options", "config"],
        },
    },
    {
        "name": "add-document-to-corpus",
        "scope": "write",
        "description": (
            "Add an already-uploaded document to a corpus by name. "
            "The document must already exist (uploaded via 'upload-document')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "corpus": {
                    "type": "string",
                    "description": "corpus name to add the document to",
                },
                "document_id": {
                    "type": "integer",
                    "description": "id of the document to add",
                },
            },
            "required": ["corpus", "document_id"],
        },
        "invocation": {
            "subcommand": "add-document-to-corpus",
            "positional": ["corpus", "document_id"],
            "options": [],
        },
    },
    {
        "name": "document-status",
        "scope": "read",
        "description": (
            "Return the current status and pipeline list for a document. "
            "Poll this after 'upload-document' or 'build-pipeline' to track "
            "background processing. Status values: received, indexing, indexed, failed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "document id to check",
                },
            },
            "required": ["document_id"],
        },
        "invocation": {
            "subcommand": "document-status",
            "positional": ["document_id"],
            "options": [],
        },
    },
]


def build_manifest() -> dict[str, Any]:
    """Return the tool manifest as a JSON-serialisable dict (a fresh shallow copy)."""
    return {"tools": [dict(tool) for tool in _TOOLS]}
