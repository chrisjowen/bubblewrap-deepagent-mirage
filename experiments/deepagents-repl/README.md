# deepagents-repl

Original agent runtime experiment. deepagents REPL with a mirage-backed workspace and bwrap-sandboxed execution.

## Contents

- `agent.py` — main REPL entrypoint.
- `runtime/` — `MirageBackend` + `MirageSandboxBackend` (mirage + bwrap + sync helpers).
- `workspace/` — local sandbox scratch dir (gitignored).

## Run

```bash
cd experiments/deepagents-repl
uv sync
uv run python agent.py
```
