## madosho document research

This workspace has madosho's RAG research tools available as skills. madosho indexes
documents into searchable corpora; these skills let an agent (or you) search and read
them and answer with citations. A corpus can also own knowledge bases (KBs) - curated
wikis of pages, distinct from indexed documents - which the same tools can search,
read, and write (semantic KB search, plus recording findings back as pages).

- To drive the tools yourself, use the `madosho-search` skill (search / search-doc
  / get-doc / list-corpora / list-documents / list-pipelines / list-goals /
  goal-runs / export-goal-run / run-goal / list-kbs / get-kb-page / search-kb /
  add-kb-page / edit-kb-page over `madosho-cli`).
- For an autonomous research pass that returns a cited report, use the
  `madosho-research` skill.
- To import an external llmkb folder as a document, or to understand the
  server-owned KB workspace in more depth, use the `madosho-kb` skill.

The tools talk to a running madosho stack. If it is not on localhost, set
MADOSHO_QUERY_URL and MADOSHO_CONTROL_URL before using the skills.
