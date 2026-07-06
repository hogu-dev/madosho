# madosho agent pack - using madosho from an agent

Copy this folder into your own project to let an agent (Claude Code, Codex, or
opencode) use madosho's document-research tools. Two modes, both portable
`SKILL.md` skills - you never call a skill by name; you describe the task and the
agent loads the matching one:

- **Mode 1 - you drive the tools** (`madosho-search`): the agent searches and
  reads a madosho corpus via `madosho-cli` and answers with citations.
- **Mode 2 - the agent returns a report** (`madosho-research`): the agent
  dispatches a subagent that follows the bundled `autonomous.md` playbook and
  hands back a finished, cited report.

This README opens with a quick start, then walks one concrete use from start to
finish, then puts the reference detail underneath.

## Quick start (Claude Code or Codex)

### 1. Have a stack up and `madosho-cli` on PATH

The skills shell out to a bare `madosho-cli`, so install madosho
(`pip install -e .` from a clone) and have a stack running (`docker compose up`).
Auth is on by default, so mint a key and export it in the shell you launch the
agent from, and point the URLs at wherever the stack runs (`madosho-host` =
`localhost` when the Docker stack is on this same machine, its hostname or IP
when it runs elsewhere):

```
docker compose exec app python -m madosho_server.keys_cli create --name agent --scope read
export MADOSHO_API_KEY=<the key it prints>
export MADOSHO_QUERY_URL=http://madosho-host:8001     # search, search-doc
export MADOSHO_CONTROL_URL=http://madosho-host:8000   # get-doc, list-corpora/documents/pipelines
```

### 2. Install the skills into your project

From the madosho repo:

```
python skills/install.py --target /path/to/your/project
```

That copies both skills into `<project>/.claude/skills/` (where Claude Code
reads them) and appends a small managed block to the project's `AGENTS.md` and
`CLAUDE.md` (append-only, never touching your own content). **Codex reads skills
from `.agents/skills`**, so for Codex also run:

```
python skills/install.py --target /path/to/your/project --skills-dir .agents/skills
```

### 3. Launch the agent in that project and just ask

```
cd /path/to/your/project
claude          # Claude Code
# or
codex           # Codex - accept the trust prompt on first run
```

Then ask in plain language, naming the corpus:

```
Search the contracts corpus for the termination clause and answer with the citation.
```

The agent matches that to `madosho-search`, runs
`madosho-cli search contracts "termination clause" --json`, reads the returned
chunks, and answers with the citation (e.g. `[contract.pdf p.1]`). For a report,
ask: `Write a short cited report on the contract terms in the contracts corpus.`
-> the agent picks `madosho-research`.

### 4. Verify the wiring (no LLM needed)

```
python skills/agent_pack_demo.py
```

Parses both skills and checks `madosho-cli` connectivity against the stack. If
it prints `OK`, the skills are ready to use.

## A concrete run

You have a madosho stack running locally and a project (call it `~/myproject`)
where you work with Claude Code. You want the agent to be able to search your
indexed documents and return cited answers.

### Step 1 - copy the pack into your project

From the madosho repo root:

```
cp -r skills ~/myproject/agent-pack
cd ~/myproject/agent-pack
python install.py --target ~/myproject
```

`install.py` does two things:

- Appends a managed block to `~/myproject/AGENTS.md` (for Codex/opencode)
  and `~/myproject/CLAUDE.md` (for Claude Code). The block is
  sentinel-delimited; your own content is never touched.
- Copies `madosho-search/` and `madosho-research/` into
  `~/myproject/.claude/skills/`.

If you later want it gone: `python install.py --target ~/myproject --uninstall`.

### Step 2 - Mode 1: you drive the tools to a cited answer

Open your project in Claude Code. Say:

  Search the "acme-reports" corpus for the total revenue figure in Q4 2024
  and give me the answer with citations.

Claude Code sees the `madosho-search` skill and runs:

```
madosho-cli list-corpora --json
madosho-cli search acme-reports "Q4 2024 revenue" --json
```

It reads the returned chunks, finds the relevant passage, and replies with the
answer and the citation string the hit provided, e.g. `[acme-q4.pdf p.7]`. You
get a grounded answer without writing any code.

### Step 3 - Mode 2: the agent returns a full report

For a longer research question, ask:

  Write me a research report on the supply-chain risks mentioned across the
  acme-reports corpus.

Claude Code invokes `madosho-research`. That skill tells Claude to
dispatch a subagent whose instructions come from the bundled
`madosho-research/autonomous.md` playbook. The subagent:

1. Orients itself with `list-corpora` and `list-documents`.
2. Runs several focused `search` rounds, refining queries to fill gaps.
3. Fetches whole documents with `get-doc` where needed.
4. Writes a markdown report with inline citations and hands it back.

You receive a finished, cited report without steering the loop yourself.

### Step 4 - server-side alternative (no host subagent)

If you prefer madosho to run its own research loop rather than dispatching a
local subagent, use `research_trigger.py`:

```
cd ~/myproject/agent-pack
python research_trigger.py \
  --corpus acme-reports \
  --prompt "Summarise the supply-chain risks" \
  --provider openai \
  --model <your-model>
```

This POSTs to madosho's `/corpora/{id}/research` endpoint, polls until the
run finishes, and prints the cited report. The LLM provider must be configured
on madosho's side, and launching a research run needs a write-scoped key. Same
`autonomous.md` playbook, same result - just running on the server instead of
your local agent host.

### Step 5 - smoke test (no LLM)

To verify the pack is wired up correctly before involving an LLM:

```
cd ~/myproject/agent-pack
python agent_pack_demo.py
```

This parses both skills (proves the files are readable and well-formed) and
calls `madosho-cli agent-tools` and `madosho-cli list-corpora` to confirm
connectivity. If both succeed, the pack is ready. Add `--with-llm --corpus
<name> --provider <p> --model <m>` to also fire a short server-side research
run.

## Reference

### Two source-of-truth files

The pack's behavior comes from exactly two files:

1. **The `agent-tools` manifest** (reported by `madosho-cli agent-tools --json`).
   This is the live list of tools with their names, descriptions, and call shapes.
   `madosho-search/SKILL.md` tells the agent how to invoke them.

2. **`autonomous.md`** (bundled as `madosho-research/autonomous.md`; the
   canonical source lives at `research_agent/autonomous.md` in the madosho repo).
   This file is the research judgment written down: orient, focused search rounds,
   get-doc when you need a whole doc, stop when you can answer, write with citations.
   `madosho-research/SKILL.md` tells the agent to read this file and pass its
   text as a subagent's instructions.

These two files are intentionally kept in sync. If you update the autonomous playbook
in `research_agent/autonomous.md`, copy it back into the pack:

```
cp research_agent/autonomous.md \
   skills/madosho-research/autonomous.md
```

### Portability: what travels and what does not

The skills use the portable `SKILL.md` core format: `name`, `description`, and a
prose body. This format works across Claude Code, Codex, and opencode.

The `allowed-tools` field (a Claude Code-specific directive that restricts which
host tools a skill may call) is NOT portable across all hosts. It is intentionally
omitted from both pack skills. If you add it for your own Claude Code setup, know
that Codex and opencode will ignore or error on it.

The `madosho-research` skill dispatches a subagent via the host's own
subagent mechanism (e.g. the Agent tool in Claude Code). That mechanism differs per
host; the skill's prose body describes what to do ("dispatch a subagent whose
instructions are the contents of `autonomous.md`") rather than naming a host-specific
call. This is intentional.

### Environment variables

Both skills drive `madosho-cli`, which reads:

| Variable              | Default                   | Used for                       |
|-----------------------|---------------------------|--------------------------------|
| MADOSHO_QUERY_URL     | http://localhost:8001     | search, search-doc             |
| MADOSHO_CONTROL_URL   | http://localhost:8000     | get-doc, list-corpora/docs/pipelines |
| MADOSHO_API_KEY       | (none)                    | Bearer key on every call (auth is on by default) |

`research_trigger.py` uses `MADOSHO_CONTROL_URL` (default `http://localhost:8000`)
and `MADOSHO_API_KEY` to POST and poll the research endpoint.

If your madosho stack is not on localhost (a home server, a cloud VM), export
the variables before running `madosho-cli` or before the agent session starts:

```
export MADOSHO_QUERY_URL=http://madosho-host:8001
export MADOSHO_CONTROL_URL=http://madosho-host:8000
export MADOSHO_API_KEY=<your key>
```

### Where skills install

`install.py` copies both skill directories into the target project's `.claude/skills/`
by default. Claude Code picks them up automatically from that path.

For Codex or opencode, pass `--skills-dir <path>` to `install.py` to place the
skills wherever your host reads them from.

To see all options: `python install.py --help`.

### Files in this pack

- `madosho-search/SKILL.md` - the tool-driving skill
- `madosho-research/SKILL.md` - the autonomous research skill
- `madosho-research/autonomous.md` - the bundled playbook
- `install.py` - idempotent installer (append-only, sentinel-delimited)
- `research_trigger.py` - server-side research trigger
- `agent_pack_demo.py` - smoke-test script
