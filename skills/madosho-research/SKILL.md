---
name: madosho-research
description: Use when you want an autonomous research pass over a madosho RAG corpus that returns a finished, cited report. Composes madosho-search and dispatches a subagent that follows the bundled autonomous.md playbook to gather evidence and write the report.
---

# Autonomous research over a madosho corpus

Use this when the goal is a finished, cited report -- not interactive tool-driving.
It builds on `madosho-search` (the same `madosho-cli` tools) and runs the
research playbook as a self-contained pass that hands back a report.

## How it runs

1. Make sure the tools are reachable (see `madosho-search` for env vars). You
   need to know the corpus name; `madosho-cli list-corpora --json` if unsure.
2. **Dispatch a subagent** whose instructions are the contents of the bundled
   `autonomous.md` (in this skill's directory). Read that file and pass its text as
   the subagent's instructions -- that file is the research judgment, written down.
   (This "dispatch a subagent with these instructions" step maps to each host's own
   subagent mechanism; it does not depend on any host-specific agent-config file.)
3. Give the subagent the research question and the corpus name, and tell it to use
   the `madosho-search` tools (`madosho-cli search` / `search-doc` / `get-doc` /
   `list-corpora` / `list-documents` / `list-pipelines`, always with `--json`).
4. The subagent runs the bounded loop in `autonomous.md` -- orient, focused search
   rounds, get-doc when it needs a whole document, stop when it can answer -- and
   returns a markdown report with inline citations.
5. Hand the report back to the user. Do not re-summarize away its citations.

## Why a subagent

The playbook is the human's judgment written down, so it attaches only to the
machine doing the autonomous work. The parent agent stays free to keep talking to
the user while the subagent gathers and writes.

## Server-side alternative

madosho can also run this exact playbook on its own server. To trigger that instead
of dispatching a local subagent, see `research_trigger.py` in this pack (it POSTs to
madosho's `/corpora/{id}/research` and polls for the report). That path needs an LLM
provider configured on madosho's side.
