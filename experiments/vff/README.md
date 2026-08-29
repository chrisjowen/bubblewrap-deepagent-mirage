# vff — virtual filesystem MCP prototype

Single-workspace FastMCP HTTP server backed by a mirage S3 workspace with a monty (Rust) Python interpreter for `execute_code`.

Superseded by [`experiments/vfs-workspace/`](../vfs-workspace/), which generalizes to multiple workspaces, adds pluggable runtimes (docker-local, code-interpreter), and adds a REST + UI on top.

## Run

```bash
cd experiments/vff
uv sync
VFF_S3_BUCKET=<bucket> VFF_S3_PREFIX=<prefix> \
    uv run python server.py
```

## Companion agent

```bash
VFF_S3_BUCKET=<bucket> VFF_S3_PREFIX=<prefix> \
    ANTHROPIC_API_KEY=... \
    uv run python agent.py "your prompt here"
```
