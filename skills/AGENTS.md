## madosho document research

This workspace has madosho's RAG research tools available as skills. madosho indexes
documents into searchable corpora; these skills let an agent (or you) search and read
them and answer with citations.

- To drive the tools yourself, use the `madosho-search` skill (search / search-doc
  / get-doc / list-corpora / list-documents / list-pipelines over `madosho-cli`).
- For an autonomous research pass that returns a cited report, use the
  `madosho-research` skill.

The tools talk to a running madosho stack. If it is not on localhost, set
MADOSHO_QUERY_URL and MADOSHO_CONTROL_URL before using the skills.
