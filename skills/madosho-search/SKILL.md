---
name: madosho-search
description: Use when you need to search or read documents in a madosho RAG corpus from the command line, to run and read madosho's autonomous alchemy goals, or to read a server-owned knowledge base. Drives madosho-cli (search, search-doc, get-doc, list-corpora, list-documents, list-pipelines, list-goals, goal-runs, export-goal-run, run-goal, list-kbs, get-kb-page, search-kb) to gather cited evidence and answer questions over indexed documents and knowledge bases.
---

# Drive madosho's document tools

madosho indexes documents into searchable corpora. This skill lets you (or you on
a user's behalf) gather evidence from a corpus using the `madosho-cli` command-line
tool, then answer with citations. There is no automation here - you are the agent;
these are the tools.

## The tools (always pass `--json`)

Run each as `madosho-cli <command> ... --json`. Under `--json`, stdout is the result
JSON or empty, and any error prints to stderr with a non-zero exit.

- `madosho-cli list-corpora --json` -> `{"corpora": [{"id", "name"}, ...]}`. Start
  here if you do not know which corpus to use.
- `madosho-cli list-documents <corpus> --json` -> `{"corpus", "documents":
  [{"id", "filename", "status", "selected_pipeline_id"}, ...]}`. Use it to find a
  document id to search within or read whole.
- `madosho-cli search <corpus> "<query>" --json` -> `{"hits": [{"text", "score",
  "citation", "source", "document_id", "position", "pipeline", "pipeline_id"}, ...]}`.
  RAG retrieval over a whole corpus - your main evidence-gathering tool. Issue
  focused queries; read the chunks; refine. Options: `--top-k N` (default 8),
  `--pipeline <name>`.
- `madosho-cli search-doc <document_id> "<query>" --json` -> same `{"hits": [...]}`
  shape as `search`, but RAG scoped to ONE document (works even for a loose
  document in no corpus). Use it to gather evidence from a single document without
  pulling in a whole corpus. Options: `--top-k N` (default 8), `--pipeline <name>`.
- `madosho-cli get-doc <document_id> --json` -> `{"document_id", "pipeline",
  "pipeline_id", "char_count", "text"}`. NOT retrieval - it loads the WHOLE
  document, in order. Use it when you need the entire document rather than scattered
  chunks. Option: `--pipeline <name>`.
- `madosho-cli list-pipelines --corpus <name> --json` (or `--document-id <id>`) ->
  `{"corpus"|"document_id", "pipelines": [{"name", "rating", "status", "effective",
  ...}, ...]}`. A document can have several pipelines (extraction/retrieval
  recipes); this lists their names so you can target one via `--pipeline`. Give
  exactly one of `--corpus` or `--document-id`.
- `madosho-cli list-goals --json` -> `[{"id", "name", "corpus_id", "goal_type",
  ...}, ...]`. Alchemy goals are named, versioned autonomous research/report
  objectives over a corpus. Start here to find the goal name to pass to the
  other goal tools.
- `madosho-cli goal-runs <goal> --json` -> `[{"version", "status", "coverage",
  "is_final", "stop_reason", "usage", ...}, ...]`, newest first. Poll this after
  `run-goal`; a run is finished when its status is done, failed, or cancelled.
- `madosho-cli export-goal-run <goal> --json` -> `{"goal", "version", "status",
  "is_final", "stop_reason", "draft_markdown", "sections": [{"key", "title",
  "filled", "confidence"}, ...], "citations"}`. One run's full draft text plus a
  slim section summary (citations is a count). Defaults to the latest run; it
  prints JSON and never writes files. Option: `--version N`.
- `madosho-cli run-goal <goal> <max_llm_calls> --json` -> `{"version", "status",
  ...}`. Starts a new run and returns immediately (needs a write-scoped key);
  poll `goal-runs`, then fetch the draft with `export-goal-run`. The LLM-call
  cap is required - never launch an uncapped run. Options: `--guidance <note>`,
  `--coverage search|full|exhaustive`, `--provider <p>`, `--model <m>`
  (provider/model default to the server's default LLM endpoint).
- `madosho-cli list-kbs --json` -> the server-owned knowledge bases (id, name,
  corpus). A KB is a corpus's own editable wiki of pages (summary / concept /
  entity) - a different thing from a searched document. Start here if you do
  not know a KB's id.
- `madosho-cli search-kb <kb_id> "<query>" --json` -> full-text search over one
  KB's pages, returning matching page summaries (title, slug, description).
- `madosho-cli get-kb-page <kb_id> <slug> --json` -> one KB page in full
  (frontmatter + body) by slug. This is a whole-page grab, not retrieval - the
  KB analog of `get-doc`. Typical flow: `list-kbs` -> `search-kb` to find a
  slug -> `get-kb-page` to read it whole.

## How to work

1. If you do not know the corpus or its documents, `list-corpora` then
   `list-documents` to orient.
2. Gather evidence with `search` (whole corpus) or `search-doc` (one document):
   focused queries, read the returned chunks, refine to fill gaps. Prefer several
   targeted searches over one broad one.
3. When you need a whole document, `get-doc` it by id.
4. Cite every claim inline using the `citation` string each hit provides, in square
   brackets, e.g. [manual.pdf p.12]. Ground claims only in what the documents say.

## Pointing at a non-local stack

The tools read `MADOSHO_QUERY_URL` (default `http://localhost:8001`) and
`MADOSHO_CONTROL_URL` (default `http://localhost:8000`). Set them if madosho is not
on localhost. If a call fails with "is the stack up?", the stack is unreachable.
