# madosho-cli

A thin, zero-dependency command-line client for a [madosho](https://github.com/hogu-dev/madosho)
RAG server. Speaks only HTTP — no kernel, database, or model imports — so it installs
in seconds and runs anywhere Python 3.11+ does.

Humans run it to inspect and drive a running madosho; a research agent drives it too
(every subcommand takes `--json`).

```
pip install madosho-cli
madosho-cli --help
madosho-cli search <corpus> "<query>" --json
```

Point it at your server with `--base-url` (default `http://localhost:8000`) and, if the
server has auth enabled, `--api-key` / `MADOSHO_API_KEY`.

Apache-2.0.
