# vfs-workspace experiment

Mirage-backed workspace service with pluggable Python/Node runtime adapters, HTTP REST + MCP surfaces, and a Svelte UI for browsing files and executing arbitrary code.

**Experiment. Not production. Minimal tests.**

**Spec:** [`../../docs/superpowers/specs/2026-08-29-vfs-workspace-design.md`](../../docs/superpowers/specs/2026-08-29-vfs-workspace-design.md)
**Plan:** [`../../docs/superpowers/plans/2026-08-29-vfs-workspace.md`](../../docs/superpowers/plans/2026-08-29-vfs-workspace.md)

## Sub-projects

| Folder | Language | Purpose |
| --- | --- | --- |
| `service/` | Python | FastAPI service + Mirage runtime adapters. |
| `runtime-image/` | Docker | Base image spawned by the `docker-local` runtime (mountpoint-s3 + Python + Node). |
| `ui/` | Node | SvelteKit + shadcn-svelte UI. |

## Running (local dev)

```bash
# 1. Build the runtime image (once, needs Docker running)
docker build -t mirage-runtime:latest experiments/vfs-workspace/runtime-image

# 2. Copy config example and edit S3 bucket / prefix
cp experiments/vfs-workspace/workspaces.yaml.example experiments/vfs-workspace/service/workspaces.yaml

# 3. Start the service on host (needs docker daemon to spawn runtime containers)
cd experiments/vfs-workspace/service
uv sync
export AWS_PROFILE=<your-profile>   # or export AWS_ACCESS_KEY_ID / SECRET / REGION
uv run uvicorn workspace_service.main:app --reload --port 8000

# 4. Start the UI (separate shell)
cd experiments/vfs-workspace/ui
pnpm install
pnpm dev   # http://localhost:5173

# 5. Smoke test
curl -H "X-User-Id: chris" http://localhost:8000/workspaces
```

## Adapters

| Runtime name | Environment | Languages |
| --- | --- | --- |
| `docker-local` | Docker container per workspace with mountpoint-s3 at `/workspace` | Python + Node |
| `code-interpreter` | Bedrock AgentCore CodeInterpreter (S3 filesystem) | Python |

Selected per user in `workspaces.yaml`.
