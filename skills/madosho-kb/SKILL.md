---
name: madosho-kb
description: Use when you want to work with a knowledge base through madosho - import a pre-made llmkb folder into a corpus as one flat document, or read/browse/search/populate a server-owned KB (a corpus's own curated wiki of pages). Complements the llmkb kb-* skills, which operate on a KB folder directly; this skill is the "through madosho" route. Covers the KB agent tools: read (list-kbs / get-kb-page / semantic search-kb) and write (add-kb-page / edit-kb-page).
---

# Work a knowledge base through madosho

madosho supports two different ways to work with a knowledge base. Pick the one
that matches what you have:

1. **Import an external llmkb folder as one flat document** - you already have a
   KB folder (from the `llmkb` tool) and want its pages searchable as a single
   madosho document.
2. **The server-owned KB workspace** - madosho owns the KB itself: a corpus can
   have several KBs, each a first-class, editable set of pages (summary /
   concept / entity) that you browse, search by meaning, read a whole page at a
   time, and write to. Page search is fused semantic + lexical retrieval;
   get-kb-page is the direct whole-page grab.

Raw documents in a corpus stay frozen either way; a KB (route 2) is the editable
member of a corpus. There is no automation here - you are the agent; these are
the tools.

## Route 1: import a pre-made KB folder as one document

Add a whole external llmkb folder as one document in a corpus:

    madosho-cli import-kb <kb-dir> --corpus <name> --json

The KB is packed into a single document (its pages become the document's content)
and ingested. Indexing/building a pipeline over it is the user's step - do not
assume it is retrievable until they have built one. Once imported and indexed,
read it like any other document with the madosho-search tools, for example:

    madosho-cli search <corpus> "<query>" --json

Read the returned chunks and cite them, the same as any other madosho document.

Recording new knowledge back into the folder is done with llmkb, the tool that
owns the KB format, so pages stay correct and lint-clean:

    llmkb get-page "<Title>" --kb <kb-dir> --json    # check for an existing page
    llmkb add-page --kb <kb-dir> --type concept --title "<Title>" \
        --description "<one line>" --source <ref> --body-file - --json

Choose type summary (one page per source), concept (synthesis), or entity (a
person, org, system, or product). Always pass --source for provenance. Prefer
refining an existing page over creating a near-duplicate. After writing, the user
re-imports the KB into madosho if they want the new pages retrievable there.

## Route 2: the server-owned KB workspace

madosho itself owns KBs: a corpus contains many KBs, each KB contains many pages
(summary | concept | entity). Storage is an llmkb-v1 folder under the server's
data directory - you never touch that folder directly, only through the tools
below or the web UI's "Knowledge bases" page (list grouped by corpus, create; a
detail page to browse pages by type and view/add/edit).

### Read tools (available to you as an agent)

These are on the agent-tools manifest, so you can call them directly:

- `madosho-cli list-kbs --json` -> the server-owned KBs (id, name, corpus). Start
  here if you do not know a KB's id.
- `madosho-cli search-kb <kb_id> "<query>" --json` -> search one KB's pages by
  meaning: fused page-level semantic + lexical (RRF) retrieval, returning matching
  page summaries (title, slug, description). Degrades to lexical-only if the KB has
  not been indexed yet.
- `madosho-cli get-kb-page <kb_id> <slug> --json` -> one page in full
  (frontmatter + body), by slug. This is a whole-page grab, not retrieval - the
  KB analog of `get-doc`.

Typical flow: `list-kbs` to find a KB id -> `search-kb` to find a page slug ->
`get-kb-page` to read it whole. Cite pages by title/slug the same way you would
cite a document chunk.

### Write tools (available to you as an agent)

`add-kb-page` and `edit-kb-page` are also on the agent-tools manifest, so you can
record durable findings back into a KB directly. Writing a page indexes it
automatically, so it is findable by `search-kb` right after. Only create or
populate a KB when a user asks you to - do not do it on your own initiative.

- `madosho-cli add-kb-page <kb_id> <type> "<title>" --json` -> write a new page.
  `type` is summary (one page per source), concept (synthesis across sources), or
  entity (a person, org, system, or product). Options: `--description "<one line>"`,
  `--tags <comma,separated>`, `--sources <comma,separated>` (or repeat `--source
  <ref>`), `--body "<text>"` (or `--body-file <path-or-->`). Set sources for
  provenance. Search the KB (`search-kb`) or read a page (`get-kb-page`) first to
  avoid a duplicate title.
- `madosho-cli edit-kb-page <kb_id> <slug> --json` -> update an existing page's
  description and/or body: `--description "<one line>"`, `--body "<text>"` (or
  `--body-file <path-or-->`). Use this instead of `add-kb-page` when a page on the
  topic already exists.

Creating a KB (`madosho-cli create-kb <corpus> <name> --json`) is a human/CLI step,
not on the agent manifest. The web UI's "Knowledge bases" page (create; browse by
type; view / add / edit / move; tags and sources) is the human route to the same KBs.
