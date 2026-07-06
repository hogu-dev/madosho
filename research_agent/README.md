# research_agent

A standalone, reusable research agent. Given a prompt, an LLM, and a set of tools
discovered from a conforming CLI, it runs a bounded retrieve-reason-retrieve loop
over a document corpus and returns a cited report.

It imports nothing from madosho. The dependency points one way: an application
depends on the agent, never the reverse. Any application is usable by the agent if
it ships a CLI that emits an `agent-tools --json` manifest and accepts `--json`
subcommands (the reuse contract, in place of MCP).

## Run it from a terminal

Point it at a running madosho (the CLI reads MADOSHO_QUERY_URL / MADOSHO_CONTROL_URL):

    python -m research_agent run \
        --prompt "How does the system described in this corpus handle sensor failures?" \
        --cli madosho-cli \
        --provider openai --model <your-model>

Flags: `--cli` is the CLI invocation to drive (whitespace-split; default
`madosho-cli`). `--provider`/`--model` are required (env fallbacks
`RESEARCH_AGENT_PROVIDER` / `RESEARCH_AGENT_MODEL`). `--api-base` and `--api-key`
configure the endpoint (`--api-key` is read from the flag or
`RESEARCH_AGENT_API_KEY` and is never printed). `--budget-chars` (default 100000)
and `--max-rounds` (default 8) bound the run. `--autonomous-md` overrides the shipped
instructions; `--out` writes the report markdown to a file.

## Use it as a library

    import research_agent
    report = research_agent.run(
        "your question",
        tools=research_agent.CliToolProvider(["madosho-cli"]),
        llm=research_agent.AnyLlmClient(
            research_agent.LlmEndpoint(provider="openai", model="<your-model>")),
    )
    print(report.markdown)
    for c in report.citations:
        print(c.citation, c.document_id, c.pipeline)

## How it is built

- `types.py` - plain dataclasses + Protocols (no LLM/HTTP types leak in).
- `tools.py` - the `ToolProvider` Protocol and `CliToolProvider` (drives any CLI).
- `llm.py` - the `LlmClient` Protocol and `AnyLlmClient` (wraps any-llm).
- `loop.py` - the retrieve-reason-retrieve loop; bounded by rounds + a char budget.
- `autonomous.md` - the default instructions (editable behaviour-as-data).
- `cli.py` - the `python -m research_agent run` entrypoint.

The loop and its tests run with a fake `ToolProvider` + a scripted `LlmClient`:
no network, no real model. See `tests/unit/test_research_agent_*.py`.
