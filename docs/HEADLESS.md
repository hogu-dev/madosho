# Headless write tools

madosho exposes document ingestion through multiple transports: CLI, HTTP, toolserver, and MCP. This guide covers the headless (API) surfaces for creating corpora, uploading documents, building pipelines, and monitoring document status.

## Write tools by transport

Three main write operations are available:

### 1. Create a corpus
**CLI:**
```bash
madosho-cli create-corpus "my-corpus"
```

**HTTP (control plane, POST):**
```
POST /corpora
{ "name": "my-corpus" }
```

Returns: `{ "id": 123, "name": "my-corpus" }`

### 2. Upload a document

**By file path (CLI or multipart library):**
```bash
madosho-cli upload-document ./nda.pdf --corpus "my-corpus"
madosho-cli upload-document ./nda.pdf --parser docling --chunker docling-hybrid
```

**HTTP (control plane, multipart):**
```
POST /corpora/{corpus_id}/documents
Content-Type: multipart/form-data

file=<binary>
parser=docling (optional)
chunker=docling-hybrid (optional)
embedder=... (optional)
```

**By base64 (HTTP, remote-friendly):**
```
POST /documents/ingest
{
  "filename": "nda.pdf",
  "content_b64": "<base64-encoded-bytes>",
  "corpus": "my-corpus" (optional),
  "parser": "docling" (optional),
  "chunker": "docling-hybrid" (optional),
  "embedder": "..." (optional)
}
```

The base64 path is recommended for remote (headless) clients, toolservers, and agent frameworks. For CLI usage, pass the file path; for programmatic/cross-network usage, base64 keeps I/O simple.

### 3. Build a named pipeline
**CLI:**
```bash
madosho-cli build-pipeline <document_id> "semantic" --chunker semantic
```

**HTTP (control plane, POST):**
```
POST /documents/{document_id}/pipelines
{
  "name": "semantic",
  "parser": "docling" (optional),
  "chunker": "semantic",
  "embedder": "..." (optional),
  "config": { ... } (optional)
}
```

Returns: `{ "id": 3, "name": "semantic", "status": "building", ... }`

## Polling and status

Document upload is **non-blocking by default** (returns 202 Accepted immediately). To wait for indexing:

**CLI (automatic blocking):**
```bash
madosho-cli upload-document ./doc.pdf --corpus "my-corpus"
# blocks until indexed, then prints final status
```

To return immediately:
```bash
madosho-cli upload-document ./doc.pdf --corpus "my-corpus" --no-wait
```

**HTTP (polling required):**
After uploading, poll the document status:
```
GET /documents/{document_id}
```

Returns: `{ "id": 42, "status": "indexing", "progress": { ... }, "pipelines": [...] }`

Status values: `received`, `indexing`, `indexed`, `failed`.

On `indexed`, all default pipelines have finished. On `failed`, the `error` field explains why.

To check a specific named pipeline:
```
GET /documents/{document_id}
# then filter pipelines[*] by name and check status
```

**Python example (stdlib-only):**
See `examples/headless/ingest.py` for a complete end-to-end flow: create corpus, ingest base64, poll until indexed, then query.

## Authentication

`MADOSHO_AUTH_ENABLED` defaults ON. All write tools require a key with
`write` scope; read operations require at least a `read` key. A fresh stack rejects
unauthenticated requests with 401 and under-scoped write attempts with 403. For an
open single-operator dev box, set `MADOSHO_AUTH_ENABLED=0` explicitly.

**CLI:**
```bash
MADOSHO_API_KEY=mdsh_abc... madosho-cli upload-document ./doc.pdf --corpus "contracts"
```

**HTTP:**
```
POST /documents/ingest
Authorization: Bearer mdsh_abc...
{ ... }
```

The `MADOSHO_API_KEY` environment variable, when set, is automatically attached to all
requests in the CLI and Python clients. If unset, the auth header is omitted (and
auth-enabled servers will return 401 for protected routes). See `docs/AUTH.md` for
minting keys.

## Reach the stack from another machine

The madosho planes listen on `0.0.0.0` by default (control `:8000`, query `:8001`,
toolserver `:8088`). The auth lock makes that safe for a trusted LAN: every call is
authenticated at the API by the caller's own key.

Set these env vars on the remote client to point at the host running the stack:

```
export MADOSHO_CONTROL_URL=http://madosho-host:8000
export MADOSHO_QUERY_URL=http://madosho-host:8001
export MADOSHO_API_KEY=mdsh_...
```

The CLI and MCP-stdio pick up all three from their environment. The toolserver and
MCP-over-HTTP act as pass-through proxies: they hold no key of their own and forward
each caller's `Authorization: Bearer` header to whichever plane they call. So scope
enforcement is always done by the actual API, not the proxy:

- A read key forwarded through the toolserver can list corpora and search (200) but
  cannot create a corpus or upload a document (403).
- A write key forwarded through the same proxy can do both.

See `examples/distributed/proof.py` for a runnable demonstration.

**TLS caveat:** keys travel as plaintext bearer tokens in HTTP headers. For exposure
over untrusted networks (internet, non-VPN cross-datacenter links), terminate TLS
in front of the stack before sending real keys off-host - the repo ships an
opt-in Caddy overlay for exactly this (`examples/tls/README.md`); any other
TLS-terminating proxy (nginx, Traefik) works too. LAN and VPN-internal
deployments are fine over plain HTTP.

## Known limitations

- Uploading a document into a corpus behaves slightly differently by transport. With a file path (CLI -> POST /corpora/{id}/documents), the corpus's own configured default recipe is used, and re-uploading a document that already exists just adds a membership link. With base64 (remote -> POST /documents/ingest with a corpus), the library default recipe is used, and re-ingesting an existing document builds an additional named pipeline. To get identical results regardless of transport, pass the parser/chunker/embedder explicitly.

- Large uploads through the multipart library endpoint (POST /documents) are currently buffered fully in memory rather than streamed. The base64 ingest path is capped at 50 MB. Streaming for the multipart library path is a planned follow-up.
