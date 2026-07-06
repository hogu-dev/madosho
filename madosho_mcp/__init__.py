"""madosho MCP server - retrieval as MCP tools (madosho never drives an LLM here).

Re-publishes the agent-tools manifest (madosho_cli.manifest) as MCP tool
definitions and delegates each call to the shared CLI orchestration core
(madosho_cli.core), so the CLI, the OpenAPI tool server, and this MCP server have
one behavior and one schema and cannot drift. Pure HTTP client - imports nothing
from the kernel or madosho_server, exactly like madosho-cli. Default transport is
stdio (an MCP host spawns `madosho-mcp`); `--http` serves streamable-HTTP.
"""
