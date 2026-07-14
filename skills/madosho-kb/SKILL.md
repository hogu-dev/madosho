---
name: madosho-kb
description: Use when you want to work with an llmkb knowledge base through madosho - import a pre-made KB into a corpus, read a KB's knowledge via madosho retrieval, or record findings back into the KB. Complements the llmkb kb-* skills, which operate on a KB folder directly; this skill is the "through madosho" route.
---

# Work a knowledge base through madosho

An llmkb knowledge base is a folder of markdown pages. madosho treats a whole KB
as one document you can add to a corpus and retrieve like any other. You can also
record findings back into the KB. Two routes exist and you may use either: the
llmkb kb-* skills (operate on the folder directly) or this skill (through
madosho). There is no automation here - you are the agent; these are the tools.

## Import a pre-made KB into madosho

Add a whole KB as one document in a corpus:

    madosho-cli import-kb <kb-dir> --corpus <name> --json

The KB is packed into a single document (its pages become the document's content)
and ingested. Indexing/building a pipeline over it is the user's step - do not
assume it is retrievable until they have built one.

## Read a KB through madosho

Once imported and indexed, the KB is a normal document. Gather evidence with the
madosho-search tools, for example:

    madosho-cli search <corpus> "<query>" --json

Read the returned chunks and cite them. This is the same retrieval you use for any
madosho document.

## Write to a KB

Recording new knowledge is done with llmkb, the tool that owns the KB format, so
pages stay correct and lint-clean:

    llmkb get-page "<Title>" --kb <kb-dir> --json    # check for an existing page
    llmkb add-page --kb <kb-dir> --type concept --title "<Title>" \
        --description "<one line>" --source <ref> --body-file - --json

Choose type summary (one page per source), concept (synthesis), or entity (a
person, org, system, or product). Always pass --source for provenance. Prefer
refining an existing page over creating a near-duplicate. After writing, the user
re-imports the KB into madosho if they want the new pages retrievable there.
