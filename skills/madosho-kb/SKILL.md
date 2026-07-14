---
name: madosho-kb
description: Use when you want to work with a knowledge base through madosho - import a pre-made llmkb folder into a corpus as one flat document, or read/browse/populate a server-owned KB (a corpus's own curated wiki of pages). Complements the llmkb kb-* skills, which operate on a KB folder directly; this skill is the "through madosho" route. Covers the read tools list-kbs / get-kb-page / search-kb.
---

# Work a knowledge base through madosho

madosho supports two different ways to work with a knowledge base. Pick the one
that matches what you have:

1. **Import an external llmkb folder as one flat document** - you already have a
   KB folder (from the `llmkb` tool) and want its pages searchable as a single
   madosho document.
2. **The server-owned KB workspace** - madosho owns the KB itself: a corpus can
   have several KBs, each a first-class, editable set of pages (summary /
   concept / entity) that you browse, search, and read a whole page at a time -
   no embedding search involved, retrieval is a direct page grab.

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
- `madosho-cli search-kb <kb_id> "<query>" --json` -> full-text search over one
  KB's pages, returning matching page summaries (title, slug, description).
- `madosho-cli get-kb-page <kb_id> <slug> --json` -> one page in full
  (frontmatter + body), by slug. This is a whole-page grab, not retrieval - the
  KB analog of `get-doc`.

Typical flow: `list-kbs` to find a KB id -> `search-kb` to find a page slug ->
`get-kb-page` to read it whole. Cite pages by title/slug the same way you would
cite a document chunk.

### CLI-only commands (human-driven; not on the agent manifest)

Creating and populating a KB is currently a human/CLI step, not something you as
an agent are asked to do (agent-populate is a later phase):

    madosho-cli create-kb <corpus> <name> --json
    madosho-cli add-kb-page <kb_id> --type <summary|concept|entity> --title "<T>" \
        [--description "<one line>"] [--tags <comma,separated>] \
        [--source <ref> ...] [--body "<text>" | --body-file <path-or-->] --json
    madosho-cli edit-kb-page <kb_id> <slug> \
        [--description "<one line>"] [--body "<text>" | --body-file <path-or-->] --json

All of these also accept `--json` like the read tools. Only use them if a user
explicitly asks you to create or populate a KB - do not create one on your own
initiative.
