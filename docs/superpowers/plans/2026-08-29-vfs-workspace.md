# VFS Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 0 of the VFS Workspace experiment — a Mirage-backed workspace service with `docker-local` + `code-interpreter` Python runtime adapters, REST + HTTP MCP surfaces, and a Svelte UI for browsing files and running arbitrary code.

**Architecture:** Extend Mirage's own runtime plugin system with three new adapter classes (docker-local Python + JS, code-interpreter Python). Wrap Mirage `Workspace` instances (one per user) inside a FastAPI service that exposes REST for the UI and HTTP MCP for a future agent. Reshuffle the repo so each existing prototype becomes an isolated experiment folder before the new work lands.

**Tech Stack:** Python 3.11 + FastAPI + FastMCP + `mirage-ai[s3]` + `boto3` (service and adapters); Docker + mountpoint-s3 (runtime image); SvelteKit 2 + Svelte 5 + shadcn-svelte + Tailwind 4 + TypeScript + pnpm (UI).

**Spec:** `docs/superpowers/specs/2026-08-29-vfs-workspace-design.md`

## Global Constraints

- Python: `>=3.11` per every experiment's `.python-version`.
- Package manager (Python): `uv`. Each experiment holds its own `pyproject.toml`, `uv.lock`, `.venv`. No shared root `pyproject.toml`.
- Package manager (JS): `pnpm`.
- Auth: `X-User-Id` HTTP header only. No OIDC/Keycloak in Phase 0.
- MCP surface: exposed but not consumed by an agent in Phase 0.
- Adapter language matrix: `docker-local` = Python + Node; `code-interpreter` = Python only.
- Runtime naming (mirage `name` classvar): `docker-local`, `code-interpreter`.
- REST base path convention: `/workspaces/{id}/...`. MCP base path convention: `/mcp/workspaces/{id}`.
- No production deployment, no Keycloak, no chat/agent, no WS streaming, no `sync-local`.
- Testing: pytest for Python, Vitest for UI; async tests via `pytest-asyncio`; mock AWS via `moto` where possible, otherwise skip with `AWS_INTEGRATION=1` env gate.

---

## File Structure

### Root
- Create: `README.md` — experiment index.
- Modify: `.gitignore` — ignore per-experiment `.venv/`, `__pycache__/`, `uv.lock`? (Keep lockfiles — reproducibility.)
- Delete: root `pyproject.toml`, root `uv.lock`, root `.python-version`, root `.venv/`, root `__pycache__/`.

### Reshuffled existing experiments
- `experiments/deepagents-repl/{pyproject.toml, uv.lock, .python-version, runtime/, agent.py, workspace/, README.md}`
- `experiments/vff/{pyproject.toml, uv.lock, .python-version, server.py, agent.py, README.md}` (existing code, new isolated project)
- `experiments/eks-agent/{pyproject.toml, uv.lock, app/, ...}` (audit needed)
- `experiments/agentcore-ada/{agentcore/, ...}` (pure infra; may not need pyproject)

### New: `experiments/vfs-workspace/`
- `README.md`
- `docker-compose.yml`
- `workspaces.yaml.example`
- `service/pyproject.toml`, `service/.python-version`
- `service/src/mirage_runtimes/__init__.py`
- `service/src/mirage_runtimes/docker_local/{__init__.py, engine.py, python.py, js.py, config.py}`
- `service/src/mirage_runtimes/code_interpreter/{__init__.py, engine.py, python.py, config.py}`
- `service/src/workspace_service/{__init__.py, main.py, config.py, workspaces.py, auth.py, models.py}`
- `service/src/workspace_service/rest/{__init__.py, files.py, exec.py, workspaces.py}`
- `service/src/workspace_service/mcp/{__init__.py, server.py}`
- `service/tests/{conftest.py, test_config.py, test_workspaces.py, test_auth.py, test_docker_local.py, test_code_interpreter.py, test_rest_files.py, test_rest_exec.py, test_mcp.py}`
- `runtime-image/{Dockerfile, entrypoint.sh}`
- `ui/package.json`, `ui/pnpm-lock.yaml`, `ui/svelte.config.js`, `ui/tailwind.config.ts`, `ui/tsconfig.json`, `ui/vite.config.ts`
- `ui/src/{app.html, app.css, lib/api.ts, lib/types.ts, lib/components/, routes/+layout.svelte, routes/+page.svelte, routes/w/[id]/+page.svelte}`

---

## Task 1: Repo reshuffle — move existing dirs into experiment folders

**Files:**
- Create: `experiments/deepagents-repl/`, `experiments/eks-agent/`, `experiments/agentcore-ada/`, `experiments/vfs-workspace/` (empty dirs)
- Move: `runtime/` → `experiments/deepagents-repl/runtime/`
- Move: `agent.py` → `experiments/deepagents-repl/agent.py`
- Move: `workspace/` → `experiments/deepagents-repl/workspace/`
- Move: `eks/` → `experiments/eks-agent/`
- Move: `ada/` → `experiments/agentcore-ada/`

**Interfaces:**
- Consumes: nothing.
- Produces: reshuffled layout; downstream tasks assume experiments live under `experiments/<name>/`.

- [ ] **Step 1: Create target experiment directories**

```bash
mkdir -p experiments/deepagents-repl experiments/eks-agent experiments/agentcore-ada experiments/vfs-workspace
```

- [ ] **Step 2: Move existing top-level dirs and files into their experiment folders**

```bash
git mv runtime experiments/deepagents-repl/runtime
git mv agent.py experiments/deepagents-repl/agent.py
git mv workspace experiments/deepagents-repl/workspace
git mv eks experiments/eks-agent
# `ada` and `eks` currently live outside experiments/ per `git status`; the
# `eks/` and `experiments/` entries in the initial `git status` were untracked
# — for those, use plain `mv` (not `git mv`) and add fresh in the next task.
```

For untracked directories flagged in `git status` (`eks/`, `experiments/`), the `git mv` above may fail — fall back to plain `mv` and the reshuffle commit picks them up as additions.

- [ ] **Step 3: Verify structure**

```bash
ls experiments/
# Expect: agentcore-ada  deepagents-repl  eks-agent  vfs-workspace  vff
find experiments -maxdepth 2 -type f | head -30
```

- [ ] **Step 4: Commit**

```bash
git add -A experiments/
git commit -m "chore: reshuffle top-level dirs into experiments/ folders

Each existing project moves under experiments/ as prep for full
per-experiment isolation. No code changes yet."
```

---

## Task 2: Extract per-experiment `pyproject.toml` files

**Files:**
- Create: `experiments/deepagents-repl/pyproject.toml`, `experiments/deepagents-repl/.python-version`
- Create: `experiments/vff/pyproject.toml`, `experiments/vff/.python-version`
- Create: `experiments/eks-agent/pyproject.toml`, `experiments/eks-agent/.python-version` (if it has Python code)
- Create: `experiments/agentcore-ada/pyproject.toml` (only if it has Python code; skip if pure infra)
- Delete: root `pyproject.toml`, root `uv.lock`, root `.python-version`, root `.venv/`, root `__pycache__/`
- Modify: root `.gitignore` — ensure `.venv/` and `__pycache__/` are ignored at any depth.

**Interfaces:**
- Consumes: reshuffled layout from Task 1.
- Produces: each experiment installable via `cd experiments/<name> && uv sync`.

- [ ] **Step 1: Audit imports per experiment**

```bash
for dir in experiments/*/; do
  echo "=== $dir ==="
  grep -rhE "^(import|from) [a-zA-Z_]+" "$dir" --include="*.py" 2>/dev/null | \
    awk '{print $2}' | cut -d. -f1 | sort -u
done
```

Record the third-party (non-stdlib) imports per experiment.

- [ ] **Step 2: Write `experiments/deepagents-repl/pyproject.toml`**

Base on root's existing deps, keep only what `experiments/deepagents-repl/` imports. Starting set (adjust per Step 1 audit):

```toml
[project]
name = "deepagents-repl"
version = "0.1.0"
description = "Original agent runtime experiment (bwrap + mirage-sync REPL)"
requires-python = ">=3.11"
dependencies = [
    "boto3>=1.40.61",
    "claude-agent-sdk>=0.1.0",
    "deepagents>=0.6.12",
    "langchain>=1.3.12,<2.0.0",
    "langchain-anthropic>=1.5.4,<2.0.0",
    "mirage-ai[s3]>=0.0.5",
    "pydantic-monty>=0.0.20",
    "python-dotenv>=1.0.0",
]
```

Also write `experiments/deepagents-repl/.python-version` with `3.11`.

- [ ] **Step 3: Write `experiments/vff/pyproject.toml`**

```toml
[project]
name = "vff"
version = "0.1.0"
description = "Virtual filesystem MCP prototype — mirage+monty over S3"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0.0",
    "mirage-ai[s3]>=0.0.5",
    "pydantic-monty>=0.0.20",
    "claude-agent-sdk>=0.1.0",
    "python-dotenv>=1.0.0",
]
```

And `experiments/vff/.python-version` = `3.11`.

- [ ] **Step 4: Handle `eks-agent` and `agentcore-ada`**

If `experiments/eks-agent/` contains Python files (`*.py`), write a `pyproject.toml` for it using the audited imports. If `experiments/agentcore-ada/` is pure JSON/CDK infra with no Python entry-points, skip its `pyproject.toml`.

Run:
```bash
find experiments/eks-agent -name "*.py" | head
find experiments/agentcore-ada -name "*.py" | head
```

For `eks-agent` if Python exists, create `pyproject.toml` with a minimal dep set (likely `mirage-ai[s3]`, `boto3`, whatever else the audit shows). For `agentcore-ada`, if no `.py` files, do not create `pyproject.toml`.

- [ ] **Step 5: Delete root Python project artifacts**

```bash
rm -rf pyproject.toml uv.lock .python-version .venv __pycache__
```

- [ ] **Step 6: Update root `.gitignore`**

Ensure these lines are present (add if missing):

```
.venv/
**/.venv/
__pycache__/
**/__pycache__/
*.pyc
node_modules/
**/node_modules/
```

Keep per-experiment `uv.lock` and `pnpm-lock.yaml` tracked (do not ignore).

- [ ] **Step 7: Run `uv sync` in each experiment**

```bash
for dir in experiments/deepagents-repl experiments/vff experiments/eks-agent; do
  if [ -f "$dir/pyproject.toml" ]; then
    echo "=== $dir ==="
    (cd "$dir" && uv sync)
  fi
done
```

Expected: each `uv sync` completes and produces `<dir>/uv.lock` and `<dir>/.venv/`.

- [ ] **Step 8: Sanity import test per experiment**

For `deepagents-repl`:
```bash
(cd experiments/deepagents-repl && uv run python -c "import runtime; print('ok')")
```
For `vff`:
```bash
(cd experiments/vff && uv run python -c "import server; print('ok')" 2>&1 | head)
```
The VFF one will fail without `VFF_S3_PREFIX` set — that's fine as long as the import error isn't a missing dep.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: extract per-experiment pyproject.toml files

Each experiment gets its own dep set, uv.lock, and .venv. Root
pyproject.toml removed. Root README added as experiment index in
next commit."
```

---

## Task 3: Root README as experiment index

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: reshuffled + per-experiment isolated layout.
- Produces: entry point documentation for the repo.

- [ ] **Step 1: Write root `README.md`**

```markdown
# agent-runtime-adapter

Umbrella repo for agent-runtime experiments. Each folder under `experiments/` is a self-contained project with its own `pyproject.toml` / `package.json` and dependencies.

## Experiments

| Folder | Language | Purpose |
| --- | --- | --- |
| [`experiments/deepagents-repl/`](experiments/deepagents-repl/) | Python | Original agent runtime adapter — deepagents REPL with mirage+bwrap sandbox. |
| [`experiments/vff/`](experiments/vff/) | Python | Virtual filesystem MCP prototype — single-workspace mirage+monty server. |
| [`experiments/eks-agent/`](experiments/eks-agent/) | Python | EKS-deployed agent (Bedrock AgentCore stub). |
| [`experiments/agentcore-ada/`](experiments/agentcore-ada/) | AWS CDK | AgentCore infrastructure declarations. |
| [`experiments/vfs-workspace/`](experiments/vfs-workspace/) | Python + TS | Multi-runtime workspace service + Svelte UI. |

Each experiment has its own `README.md` with run instructions.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: root README as experiment index"
```

---

## Task 4: Scaffold `experiments/vfs-workspace/` skeleton

**Files:**
- Create: `experiments/vfs-workspace/README.md`
- Create: `experiments/vfs-workspace/docker-compose.yml`
- Create: `experiments/vfs-workspace/workspaces.yaml.example`
- Create: `experiments/vfs-workspace/service/pyproject.toml`, `service/.python-version`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/__init__.py` (empty)
- Create: `experiments/vfs-workspace/service/src/workspace_service/__init__.py` (empty)
- Create: `experiments/vfs-workspace/service/tests/__init__.py`
- Create: `experiments/vfs-workspace/runtime-image/` (empty dir, populated later)
- Create: `experiments/vfs-workspace/ui/` (populated by SvelteKit scaffold)

**Interfaces:**
- Consumes: nothing.
- Produces: importable `mirage_runtimes` and `workspace_service` packages inside `experiments/vfs-workspace/service/`.

- [ ] **Step 1: Write `experiments/vfs-workspace/README.md`**

```markdown
# vfs-workspace experiment

Mirage-backed workspace service with pluggable Python/Node runtime adapters, HTTP REST + MCP surfaces, and a Svelte UI for browsing files and executing arbitrary code.

**Spec:** [`../../docs/superpowers/specs/2026-08-29-vfs-workspace-design.md`](../../docs/superpowers/specs/2026-08-29-vfs-workspace-design.md)

## Sub-projects

- `service/` — Python: FastAPI service, Mirage runtime adapters.
- `runtime-image/` — Docker: base image used by the `docker-local` runtime.
- `ui/` — Node: SvelteKit + shadcn-svelte UI.

## Running (local dev)

```bash
# 1. Build the runtime container image (once)
docker build -t mirage-runtime:latest experiments/vfs-workspace/runtime-image

# 2. Copy example config and edit S3 bucket/prefix
cp experiments/vfs-workspace/workspaces.yaml.example experiments/vfs-workspace/service/workspaces.yaml

# 3. Start the service (host process — needs docker daemon to spawn runtimes)
cd experiments/vfs-workspace/service
export AWS_PROFILE=<your-profile>
uv sync
uv run uvicorn workspace_service.main:app --reload --port 8000

# 4. Start the UI (separate shell)
cd experiments/vfs-workspace/ui
pnpm install
pnpm dev  # http://localhost:5173

# 5. Smoke test
curl -H "X-User-Id: chris" http://localhost:8000/workspaces
```
```

- [ ] **Step 2: Write `experiments/vfs-workspace/service/pyproject.toml`**

```toml
[project]
name = "workspace-service"
version = "0.1.0"
description = "Mirage-backed workspace service with pluggable runtime adapters"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "fastmcp>=2.0.0",
    "mirage-ai[s3]>=0.0.5",
    "boto3>=1.40.61",
    "pyyaml>=6.0.2",
    "pydantic>=2.9.0",
    "python-dotenv>=1.0.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "moto[s3]>=5.0.0",
    "httpx>=0.28.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.uv]
package = false

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mirage_runtimes", "src/workspace_service"]
```

Also `.python-version`:
```
3.11
```

- [ ] **Step 3: Create empty package `__init__.py` files**

```bash
mkdir -p experiments/vfs-workspace/service/src/mirage_runtimes
mkdir -p experiments/vfs-workspace/service/src/workspace_service
mkdir -p experiments/vfs-workspace/service/tests
touch experiments/vfs-workspace/service/src/mirage_runtimes/__init__.py
touch experiments/vfs-workspace/service/src/workspace_service/__init__.py
touch experiments/vfs-workspace/service/tests/__init__.py
```

- [ ] **Step 4: Write `workspaces.yaml.example`**

```yaml
# Copy to workspaces.yaml and edit for your setup.
# Auth: X-User-Id header only for Phase 0.
users:
  chris:
    s3_bucket: mirage-test-chris
    s3_region: ap-southeast-1
    s3_prefix: workspaces/chris
    runtime: docker-local
    mount_name: disk
  demo:
    s3_bucket: mirage-test-chris
    s3_region: ap-southeast-1
    s3_prefix: workspaces/demo
    runtime: code-interpreter
    mount_name: disk

runtimes:
  docker-local:
    image: mirage-runtime:latest
    aws_env_forwarding: true
  code-interpreter:
    agentcore_region: us-east-1
    session_timeout_seconds: 900
```

- [ ] **Step 5: Write `docker-compose.yml` (UI only; service runs on host)**

```yaml
version: "3.9"
services:
  ui:
    image: node:22-alpine
    working_dir: /app
    volumes:
      - ./ui:/app
    ports:
      - "5173:5173"
    environment:
      PUBLIC_API_BASE: http://host.docker.internal:8000
      PUBLIC_USER_ID: chris
    command: sh -c "corepack enable && pnpm install && pnpm dev --host 0.0.0.0"
```

(Service is not composed — it needs to launch sibling docker containers, which is fragile inside compose without docker-outside-docker. Run service on host with `uv run`.)

- [ ] **Step 6: `uv sync` the service**

```bash
cd experiments/vfs-workspace/service
uv sync
```

Expected: `uv.lock` and `.venv/` produced, no errors.

- [ ] **Step 7: Verify imports**

```bash
cd experiments/vfs-workspace/service
uv run python -c "import mirage_runtimes; import workspace_service; print('ok')"
```

Expected: `ok`.

- [ ] **Step 8: Commit**

```bash
git add experiments/vfs-workspace/
git commit -m "chore: scaffold vfs-workspace experiment skeleton

Empty packages, pyproject.toml, README, docker-compose (UI only),
and workspaces.yaml example. No functionality yet."
```

---

## Task 5: Runtime container image (`runtime-image/`)

**Files:**
- Create: `experiments/vfs-workspace/runtime-image/Dockerfile`
- Create: `experiments/vfs-workspace/runtime-image/entrypoint.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: docker image tag `mirage-runtime:latest` with `mountpoint-s3`, Python 3, Node 20 pre-installed. Container mounts S3 at `/workspace` on start using env vars.

- [ ] **Step 1: Write `runtime-image/entrypoint.sh`**

```bash
#!/bin/sh
set -e

: "${S3_BUCKET:?S3_BUCKET env var required}"
: "${S3_PREFIX:?S3_PREFIX env var required}"

MOUNT_DIR="${MOUNT_DIR:-/workspace}"
mkdir -p "$MOUNT_DIR"

# --foreground keeps mount-s3 alive; run it as a background process so
# the container's PID 1 can serve exec calls afterwards.
mount-s3 \
  "$S3_BUCKET" "$MOUNT_DIR" \
  --prefix "${S3_PREFIX%/}/" \
  --metadata-ttl 0 \
  --allow-delete \
  --allow-overwrite \
  --foreground &

MOUNT_PID=$!

# Wait until mount is live (poll for up to 15s).
for i in $(seq 1 30); do
  if mountpoint -q "$MOUNT_DIR"; then
    break
  fi
  sleep 0.5
done

if ! mountpoint -q "$MOUNT_DIR"; then
  echo "mount-s3 failed to mount $MOUNT_DIR" >&2
  exit 1
fi

# Trap so container teardown unmounts cleanly.
cleanup() {
  fusermount -u "$MOUNT_DIR" 2>/dev/null || umount "$MOUNT_DIR" 2>/dev/null || true
  kill "$MOUNT_PID" 2>/dev/null || true
  wait "$MOUNT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec "$@"
```

Make executable in Step 2's Dockerfile via `RUN chmod +x`.

- [ ] **Step 2: Write `runtime-image/Dockerfile`**

```dockerfile
FROM public.ecr.aws/lts/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates fuse \
      python3 python3-pip python3-venv \
      util-linux \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# Install mountpoint-s3 (arch-aware).
RUN ARCH=$(uname -m) \
 && case "$ARCH" in \
      x86_64)  MS_ARCH=x86_64 ;; \
      aarch64) MS_ARCH=arm64 ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/mount-s3.deb "https://s3.amazonaws.com/mountpoint-s3-release/latest/${MS_ARCH}/mount-s3.deb" \
 && dpkg -i /tmp/mount-s3.deb \
 && rm /tmp/mount-s3.deb

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
```

- [ ] **Step 3: Build image**

```bash
docker build -t mirage-runtime:latest experiments/vfs-workspace/runtime-image
```

Expected: image builds; final size ~500-700 MB.

- [ ] **Step 4: Smoke test — mount + exec**

Assuming AWS creds are exported in current shell (`AWS_ACCESS_KEY_ID`, etc.) and a test bucket + prefix exist:

```bash
docker run --rm -d \
  --name mirage-smoke \
  --cap-add SYS_ADMIN --device /dev/fuse \
  -e S3_BUCKET="$TEST_BUCKET" \
  -e S3_PREFIX="$TEST_PREFIX" \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e AWS_REGION \
  mirage-runtime:latest

# Wait for mount
sleep 3

docker exec mirage-smoke ls /workspace
docker exec mirage-smoke python3 -c "import os; print(os.listdir('/workspace'))"
docker exec mirage-smoke node -e "console.log(require('fs').readdirSync('/workspace'))"

docker stop mirage-smoke
```

Expected: all three commands print the S3 prefix's top-level entries. If mount fails, iterate on `entrypoint.sh`.

- [ ] **Step 5: Commit**

```bash
git add experiments/vfs-workspace/runtime-image/
git commit -m "feat(runtime-image): docker base image with mountpoint-s3 + py + node

Builds mirage-runtime:latest. Entry script mounts S3 at /workspace
using S3_BUCKET + S3_PREFIX env vars, then execs CMD."
```

---

## Task 6: `docker-local` adapter — engine

**Files:**
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/__init__.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/config.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/engine.py`
- Create: `experiments/vfs-workspace/service/tests/test_docker_local_engine.py`

**Interfaces:**
- Consumes: mirage `RunArgs`, `RunResult` from `mirage.runtime.types`.
- Produces:
  - `DockerLocalConfig(BaseModel)` — pydantic config: `s3_bucket: str`, `s3_prefix: str`, `image: str = "mirage-runtime:latest"`, `aws_env_forwarding: bool = True`.
  - `DockerLocalEngine`:
    - `__init__(config: DockerLocalConfig)`
    - `start() -> None` — spawn container, wait for mount, raise `RuntimeError` on failure.
    - `async run(interpreter: str, args: RunArgs) -> RunResult` — `docker exec -i <name> <interpreter> -c <code>`.
    - `stop() -> None` — `docker stop`.
    - `container_name: str` (read-only property).

- [ ] **Step 1: Write `docker_local/config.py`**

```python
from pydantic import BaseModel, Field


class DockerLocalConfig(BaseModel):
    s3_bucket: str
    s3_prefix: str
    image: str = "mirage-runtime:latest"
    aws_env_forwarding: bool = True
    startup_timeout_seconds: float = Field(default=15.0, gt=0)
    mount_dir: str = "/workspace"
```

- [ ] **Step 2: Write failing test — engine start/stop lifecycle**

```python
# tests/test_docker_local_engine.py
import os
import subprocess
import pytest

from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine


pytestmark = pytest.mark.skipif(
    os.environ.get("DOCKER_INTEGRATION") != "1",
    reason="set DOCKER_INTEGRATION=1 and provide AWS_* + TEST_BUCKET/PREFIX to run",
)


@pytest.fixture
def engine():
    cfg = DockerLocalConfig(
        s3_bucket=os.environ["TEST_BUCKET"],
        s3_prefix=os.environ["TEST_PREFIX"],
    )
    e = DockerLocalEngine(cfg)
    e.start()
    yield e
    e.stop()


def test_container_starts_and_mount_is_live(engine):
    proc = subprocess.run(
        ["docker", "exec", engine.container_name, "mountpoint", "-q", "/workspace"],
        capture_output=True,
    )
    assert proc.returncode == 0
```

- [ ] **Step 3: Run test to confirm import error**

```bash
cd experiments/vfs-workspace/service
DOCKER_INTEGRATION=1 TEST_BUCKET=fake TEST_PREFIX=fake uv run pytest tests/test_docker_local_engine.py -v
```
Expected: FAIL (module not found — `mirage_runtimes.docker_local.engine`).

- [ ] **Step 4: Write `docker_local/engine.py`**

```python
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from uuid import uuid4

from mirage.runtime.types import RunArgs, RunResult

from mirage_runtimes.docker_local.config import DockerLocalConfig


_AWS_ENV_KEYS = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
)


def _aws_env_from_host() -> dict[str, str]:
    return {k: os.environ[k] for k in _AWS_ENV_KEYS if k in os.environ}


class DockerLocalEngine:
    def __init__(self, config: DockerLocalConfig) -> None:
        self._config = config
        self._container_name = f"mirage-ws-{uuid4().hex[:8]}"
        self._started = False

    @property
    def container_name(self) -> str:
        return self._container_name

    def start(self) -> None:
        env_flags: list[str] = ["-e", f"S3_BUCKET={self._config.s3_bucket}",
                                "-e", f"S3_PREFIX={self._config.s3_prefix}"]
        if self._config.aws_env_forwarding:
            for k, v in _aws_env_from_host().items():
                env_flags.extend(["-e", f"{k}={v}"])

        cmd = [
            "docker", "run", "-d", "--rm",
            "--name", self._container_name,
            "--cap-add", "SYS_ADMIN",
            "--device", "/dev/fuse",
            "--security-opt", "apparmor:unconfined",
            *env_flags,
            self._config.image,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"docker run failed: {result.stderr}")

        # Wait for the mount to become live inside the container.
        deadline = time.monotonic() + self._config.startup_timeout_seconds
        while time.monotonic() < deadline:
            check = subprocess.run(
                ["docker", "exec", self._container_name,
                 "mountpoint", "-q", self._config.mount_dir],
                capture_output=True,
            )
            if check.returncode == 0:
                self._started = True
                return
            time.sleep(0.25)

        self.stop()
        raise RuntimeError(
            f"mount at {self._config.mount_dir} did not become live within "
            f"{self._config.startup_timeout_seconds}s"
        )

    async def run(self, interpreter: str, args: RunArgs) -> RunResult:
        if not self._started:
            raise RuntimeError("engine not started")

        env_flags: list[str] = []
        for k, v in args.env.items():
            env_flags.extend(["-e", f"{k}={v}"])

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", *env_flags, self._container_name,
            interpreter, "-c", args.code, *args.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate(input=args.stdin)
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

        return RunResult(
            stdout=stdout,
            stderr=stderr or None,
            exit_code=proc.returncode if proc.returncode is not None else 1,
        )

    def stop(self) -> None:
        if not self._container_name:
            return
        subprocess.run(
            ["docker", "stop", "-t", "5", self._container_name],
            capture_output=True, timeout=15,
        )
        self._started = False
```

Also write `docker_local/__init__.py`:
```python
from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine

__all__ = ["DockerLocalConfig", "DockerLocalEngine"]
```

- [ ] **Step 5: Run integration test** (requires docker + AWS)

```bash
cd experiments/vfs-workspace/service
DOCKER_INTEGRATION=1 \
  TEST_BUCKET=<your-bucket> TEST_PREFIX=<your-prefix> \
  AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=... \
  uv run pytest tests/test_docker_local_engine.py -v
```
Expected: PASS.

If test can't run in the executor's environment, mark expected outcome as "SKIPPED (DOCKER_INTEGRATION not set)" and document that manual smoke test in Task 5 Step 4 proves the image; adapter engine correctness is covered by the exec test in Task 7.

- [ ] **Step 6: Add unit test that mocks `subprocess.run` for start-failure path**

```python
def test_start_raises_on_docker_failure(monkeypatch):
    from mirage_runtimes.docker_local import engine as eng

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)

    e = DockerLocalEngine(DockerLocalConfig(s3_bucket="b", s3_prefix="p"))
    with pytest.raises(RuntimeError, match="docker run failed: boom"):
        e.start()
```

Run:
```bash
uv run pytest tests/test_docker_local_engine.py::test_start_raises_on_docker_failure -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/ \
        experiments/vfs-workspace/service/tests/test_docker_local_engine.py
git commit -m "feat(docker-local): engine — container start/exec/stop over mount-s3"
```

---

## Task 7: `docker-local` adapter — Python + JS runtime subclasses

**Files:**
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/python.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/js.py`
- Modify: `experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/__init__.py`
- Create: `experiments/vfs-workspace/service/tests/test_docker_local_runtimes.py`

**Interfaces:**
- Consumes: `DockerLocalConfig`, `DockerLocalEngine` from Task 6.
- Produces:
  - `MountLocalPython(PythonRuntime)` — `name = "docker-local"`, `reach = "process"`, `config_cls = DockerLocalConfig`. Constructor starts engine; `run(args)` calls engine's Python subprocess; `__del__` stops engine.
  - `MountLocalJs(JsRuntime)` — same shape, interpreter `node`.

- [ ] **Step 1: Write failing exec test (integration)**

```python
# tests/test_docker_local_runtimes.py
import os
import pytest

from mirage.runtime.types import RunArgs

from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.python import MountLocalPython
from mirage_runtimes.docker_local.js import MountLocalJs


pytestmark = pytest.mark.skipif(
    os.environ.get("DOCKER_INTEGRATION") != "1",
    reason="requires docker + AWS creds",
)


@pytest.fixture
def cfg():
    return DockerLocalConfig(
        s3_bucket=os.environ["TEST_BUCKET"],
        s3_prefix=os.environ["TEST_PREFIX"],
    )


@pytest.mark.asyncio
async def test_python_hello(cfg):
    rt = MountLocalPython(config=cfg)
    try:
        result = await rt.run(RunArgs(code="print('hello from python')"))
        assert result.exit_code == 0
        assert b"hello from python" in result.stdout
    finally:
        rt._engine.stop()


@pytest.mark.asyncio
async def test_node_hello(cfg):
    rt = MountLocalJs(config=cfg)
    try:
        result = await rt.run(RunArgs(code="console.log('hello from node')"))
        assert result.exit_code == 0
        assert b"hello from node" in result.stdout
    finally:
        rt._engine.stop()
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd experiments/vfs-workspace/service
DOCKER_INTEGRATION=1 uv run pytest tests/test_docker_local_runtimes.py -v
```
Expected: FAIL (module not found).

- [ ] **Step 3: Write `docker_local/python.py`**

```python
from __future__ import annotations

from typing import Any, ClassVar

from mirage.runtime.python.base import PythonRuntime
from mirage.runtime.types import RunArgs, RunResult, RuntimeReach

from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine


class MountLocalPython(PythonRuntime):
    name = "docker-local"
    reach: RuntimeReach = "process"
    config_cls: ClassVar[type] = DockerLocalConfig
    config: DockerLocalConfig

    def __init__(
        self,
        captures=None,
        config: DockerLocalConfig | dict[str, Any] | None = None,
        script=None,
    ) -> None:
        super().__init__(captures, config, script)
        if isinstance(self.config, dict):
            self.config = DockerLocalConfig(**self.config)
        self._engine = DockerLocalEngine(self.config)
        self._engine.start()

    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run("python3", args)

    def __del__(self) -> None:
        try:
            self._engine.stop()
        except Exception:
            pass
```

- [ ] **Step 4: Write `docker_local/js.py`**

```python
from __future__ import annotations

from typing import Any, ClassVar

from mirage.runtime.js.base import JsRuntime  # verify path — see step 5
from mirage.runtime.types import RunArgs, RunResult, RuntimeReach

from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine


class MountLocalJs(JsRuntime):
    name = "docker-local"
    reach: RuntimeReach = "process"
    config_cls: ClassVar[type] = DockerLocalConfig
    config: DockerLocalConfig

    def __init__(
        self,
        captures=None,
        config: DockerLocalConfig | dict[str, Any] | None = None,
        script=None,
    ) -> None:
        super().__init__(captures, config, script)
        if isinstance(self.config, dict):
            self.config = DockerLocalConfig(**self.config)
        self._engine = DockerLocalEngine(self.config)
        self._engine.start()

    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run("node", args)

    def __del__(self) -> None:
        try:
            self._engine.stop()
        except Exception:
            pass
```

- [ ] **Step 5: Verify `mirage.runtime.js.base` import path is correct**

```bash
uv run python -c "from mirage.runtime.js.base import JsRuntime; print(JsRuntime.__mro__)"
```
If path differs (e.g. `mirage.runtime.js.JsRuntime`), adjust the import in Step 4. If a `JsRuntime` symbol doesn't exist as a base class (only `QuickJsRuntime` or similar), subclass whatever the actual JS-tier base is; check `.venv/lib/python3.11/site-packages/mirage/runtime/js/*.py`.

- [ ] **Step 6: Update `docker_local/__init__.py`**

```python
from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine
from mirage_runtimes.docker_local.python import MountLocalPython
from mirage_runtimes.docker_local.js import MountLocalJs

__all__ = ["DockerLocalConfig", "DockerLocalEngine",
           "MountLocalPython", "MountLocalJs"]
```

- [ ] **Step 7: Run the integration tests**

```bash
cd experiments/vfs-workspace/service
DOCKER_INTEGRATION=1 TEST_BUCKET=... TEST_PREFIX=... AWS_*=... \
  uv run pytest tests/test_docker_local_runtimes.py -v
```
Expected: 2 PASS. If runtime instantiation without a workspace fails (mirage may require the runtime to be attached to a workspace before use), skip these and defer testing to the workspace-level integration test in Task 15.

- [ ] **Step 8: Commit**

```bash
git add experiments/vfs-workspace/service/src/mirage_runtimes/docker_local/ \
        experiments/vfs-workspace/service/tests/test_docker_local_runtimes.py
git commit -m "feat(docker-local): Python + Node runtime subclasses"
```

---

## Task 8: `code-interpreter` adapter — engine + Python runtime

**Files:**
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/code_interpreter/__init__.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/code_interpreter/config.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/code_interpreter/engine.py`
- Create: `experiments/vfs-workspace/service/src/mirage_runtimes/code_interpreter/python.py`
- Create: `experiments/vfs-workspace/service/tests/test_code_interpreter.py`

**Interfaces:**
- Consumes: mirage `PythonRuntime`, `RunArgs`, `RunResult`, `RuntimeReach`.
- Produces:
  - `CodeInterpreterConfig(BaseModel)` — `region: str`, `s3_bucket: str`, `s3_prefix: str`, `session_timeout_seconds: int = 900`.
  - `CodeInterpreterEngine` — `open()`, `async run(args: RunArgs) -> RunResult`, `close()`. `_client` uses `boto3.client("bedrock-agentcore-control")` (verify at implementation time).
  - `CodeInterpreterPython(PythonRuntime)` — `name = "code-interpreter"`, `reach = "remote"`, mount config → engine at `__init__`.

- [ ] **Step 1: Confirm AgentCore CodeInterpreter boto3 shapes**

```bash
uv run python -c "import boto3; print(sorted([s for s in boto3.Session().get_available_services() if 'agent' in s or 'bedrock' in s]))"
```
Then inspect the chosen client:
```bash
uv run python -c "import boto3; c = boto3.client('bedrock-agentcore-control', region_name='us-east-1'); print([op for op in dir(c) if 'code' in op.lower() or 'interpret' in op.lower()])"
```
Record the actual method names for session create/execute/delete. Update the engine code in Step 4 accordingly. If the service name is different (e.g. `bedrock-agentcore` vs `bedrock-agentcore-control`), use whichever exposes the code-interpreter operations.

- [ ] **Step 2: Write `code_interpreter/config.py`**

```python
from pydantic import BaseModel, Field


class CodeInterpreterConfig(BaseModel):
    region: str
    s3_bucket: str
    s3_prefix: str
    session_timeout_seconds: int = Field(default=900, gt=0)
```

- [ ] **Step 3: Write failing test — engine open + run + close (mocked boto)**

```python
# tests/test_code_interpreter.py
import pytest
from unittest.mock import MagicMock, patch

from mirage.runtime.types import RunArgs

from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig
from mirage_runtimes.code_interpreter.engine import CodeInterpreterEngine


@pytest.fixture
def cfg():
    return CodeInterpreterConfig(region="us-east-1", s3_bucket="b", s3_prefix="p/")


@pytest.mark.asyncio
async def test_engine_open_run_close(cfg):
    with patch("mirage_runtimes.code_interpreter.engine.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.create_code_interpreter_session.return_value = {"sessionId": "s-123"}
        client.execute_code.return_value = {
            "stdout": "42\n", "stderr": "", "exitCode": 0,
        }

        engine = CodeInterpreterEngine(cfg)
        engine.open()
        assert client.create_code_interpreter_session.called

        result = await engine.run(RunArgs(code="print(6*7)"))
        assert result.exit_code == 0
        assert result.stdout == b"42\n"

        engine.close()
        client.delete_code_interpreter_session.assert_called_once_with(sessionId="s-123")
```

- [ ] **Step 4: Run test to confirm failure**

```bash
cd experiments/vfs-workspace/service
uv run pytest tests/test_code_interpreter.py::test_engine_open_run_close -v
```
Expected: FAIL (module not found).

- [ ] **Step 5: Write `code_interpreter/engine.py`**

```python
from __future__ import annotations

import asyncio

import boto3

from mirage.runtime.types import RunArgs, RunResult

from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig


class CodeInterpreterEngine:
    """AgentCore CodeInterpreter session wrapper.

    The exact boto3 method names below (`create_code_interpreter_session`,
    `execute_code`, `delete_code_interpreter_session`) are the current best
    guess based on the AgentCore surface. Verify against your boto3
    version's operation list (see Task 8 Step 1) and adjust here — the
    caller-facing engine API stays the same.
    """

    _SERVICE_NAME = "bedrock-agentcore-control"

    def __init__(self, config: CodeInterpreterConfig) -> None:
        self._config = config
        self._client = boto3.client(self._SERVICE_NAME, region_name=config.region)
        self._session_id: str | None = None

    def open(self) -> None:
        resp = self._client.create_code_interpreter_session(
            fileSystemConfig={
                "s3": {
                    "bucketName": self._config.s3_bucket,
                    "prefix": self._config.s3_prefix,
                }
            },
            sessionTimeoutSeconds=self._config.session_timeout_seconds,
        )
        self._session_id = resp["sessionId"]

    async def run(self, args: RunArgs) -> RunResult:
        if not self._session_id:
            raise RuntimeError("engine not open")
        resp = await asyncio.to_thread(
            self._client.execute_code,
            sessionId=self._session_id,
            code=args.code,
            language="python",
        )
        stdout = resp.get("stdout", "").encode() if isinstance(resp.get("stdout"), str) else resp.get("stdout", b"")
        stderr = resp.get("stderr") or None
        if isinstance(stderr, str):
            stderr = stderr.encode() or None
        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=int(resp.get("exitCode", 0)),
        )

    def close(self) -> None:
        if self._session_id:
            try:
                self._client.delete_code_interpreter_session(sessionId=self._session_id)
            finally:
                self._session_id = None
```

- [ ] **Step 6: Run test — should PASS**

```bash
uv run pytest tests/test_code_interpreter.py::test_engine_open_run_close -v
```
Expected: PASS. If the test still fails because real boto3 call signatures differ from placeholder names, adjust engine methods to match what Step 1 uncovered and re-run.

- [ ] **Step 7: Write `code_interpreter/python.py`**

```python
from __future__ import annotations

from typing import Any, ClassVar

from mirage.runtime.python.base import PythonRuntime
from mirage.runtime.types import RunArgs, RunResult, RuntimeReach

from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig
from mirage_runtimes.code_interpreter.engine import CodeInterpreterEngine


class CodeInterpreterPython(PythonRuntime):
    name = "code-interpreter"
    reach: RuntimeReach = "remote"
    config_cls: ClassVar[type] = CodeInterpreterConfig
    config: CodeInterpreterConfig

    def __init__(
        self,
        captures=None,
        config: CodeInterpreterConfig | dict[str, Any] | None = None,
        script=None,
    ) -> None:
        super().__init__(captures, config, script)
        if isinstance(self.config, dict):
            self.config = CodeInterpreterConfig(**self.config)
        self._engine = CodeInterpreterEngine(self.config)
        self._engine.open()

    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run(args)

    def __del__(self) -> None:
        try:
            self._engine.close()
        except Exception:
            pass
```

- [ ] **Step 8: Write `code_interpreter/__init__.py`**

```python
from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig
from mirage_runtimes.code_interpreter.engine import CodeInterpreterEngine
from mirage_runtimes.code_interpreter.python import CodeInterpreterPython

__all__ = ["CodeInterpreterConfig", "CodeInterpreterEngine", "CodeInterpreterPython"]
```

- [ ] **Step 9: Add subclass test that mocks the engine**

```python
def test_python_subclass_delegates_to_engine(monkeypatch):
    from mirage_runtimes.code_interpreter.python import CodeInterpreterPython
    from mirage_runtimes.code_interpreter import python as py_mod

    calls = {}

    class FakeEngine:
        def __init__(self, cfg): calls["init"] = cfg
        def open(self): calls["open"] = True
        async def run(self, args): calls["run"] = args; return RunResult(b"x", None, 0)
        def close(self): calls["close"] = True

    monkeypatch.setattr(py_mod, "CodeInterpreterEngine", FakeEngine)

    rt = CodeInterpreterPython(config=CodeInterpreterConfig(
        region="us-east-1", s3_bucket="b", s3_prefix="p/",
    ))
    assert calls["open"] is True
```

Run:
```bash
uv run pytest tests/test_code_interpreter.py -v
```
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add experiments/vfs-workspace/service/src/mirage_runtimes/code_interpreter/ \
        experiments/vfs-workspace/service/tests/test_code_interpreter.py
git commit -m "feat(code-interpreter): AgentCore CodeInterpreter runtime adapter"
```

---

## Task 9: Config loader — user + runtime YAML → pydantic models

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/config.py`
- Create: `experiments/vfs-workspace/service/tests/test_config.py`

**Interfaces:**
- Produces:
  - `UserSpec(BaseModel)` — `s3_bucket, s3_region, s3_prefix, runtime, mount_name`.
  - `DockerLocalRuntimeSpec(BaseModel)` — `image, aws_env_forwarding`.
  - `CodeInterpreterRuntimeSpec(BaseModel)` — `agentcore_region, session_timeout_seconds`.
  - `WorkspacesConfig(BaseModel)` — `users: dict[str, UserSpec]`, `runtimes: dict[str, dict]` (loosely typed to support future runtimes).
  - `load_config(path: Path) -> WorkspacesConfig`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import textwrap
from pathlib import Path

import pytest

from workspace_service.config import load_config


def test_load_config_parses_users_and_runtimes(tmp_path: Path):
    (tmp_path / "workspaces.yaml").write_text(textwrap.dedent("""
        users:
          chris:
            s3_bucket: b
            s3_region: r
            s3_prefix: p
            runtime: docker-local
            mount_name: disk
        runtimes:
          docker-local:
            image: mirage-runtime:latest
            aws_env_forwarding: true
    """).strip())

    cfg = load_config(tmp_path / "workspaces.yaml")

    assert "chris" in cfg.users
    assert cfg.users["chris"].runtime == "docker-local"
    assert cfg.runtimes["docker-local"]["image"] == "mirage-runtime:latest"


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_config.py -v
```
Expected: FAIL (module not found).

- [ ] **Step 3: Write `config.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


RuntimeName = Literal["docker-local", "code-interpreter"]


class UserSpec(BaseModel):
    s3_bucket: str
    s3_region: str
    s3_prefix: str
    runtime: RuntimeName
    mount_name: str = "disk"


class WorkspacesConfig(BaseModel):
    users: dict[str, UserSpec]
    runtimes: dict[str, dict] = {}


def load_config(path: Path) -> WorkspacesConfig:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return WorkspacesConfig.model_validate(data)
```

- [ ] **Step 4: Run test — expect PASS**

```bash
uv run pytest tests/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/config.py \
        experiments/vfs-workspace/service/tests/test_config.py
git commit -m "feat(config): YAML → pydantic user/runtime spec"
```

---

## Task 10: Auth middleware — `X-User-Id` header

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/auth.py`
- Create: `experiments/vfs-workspace/service/tests/test_auth.py`

**Interfaces:**
- Consumes: `WorkspacesConfig` (to validate user exists).
- Produces:
  - `get_current_user(request: Request, config: WorkspacesConfig) -> str` — FastAPI dependency raising 401 on missing header, 403 on unknown user.

- [ ] **Step 1: Write failing test**

```python
# tests/test_auth.py
import pytest
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient

from workspace_service.config import WorkspacesConfig, UserSpec
from workspace_service.auth import get_current_user


def _app_with_config(cfg: WorkspacesConfig) -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: str = Depends(lambda: get_current_user)):
        # placeholder — real wiring via dependency factory in production code
        raise NotImplementedError

    return app


def test_missing_header_401():
    cfg = WorkspacesConfig(users={"chris": UserSpec(
        s3_bucket="b", s3_region="r", s3_prefix="p", runtime="docker-local")})
    from workspace_service.auth import make_current_user_dep

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: str = Depends(make_current_user_dep(cfg))):
        return {"user": user}

    client = TestClient(app)
    resp = client.get("/whoami")
    assert resp.status_code == 401


def test_unknown_user_403():
    cfg = WorkspacesConfig(users={"chris": UserSpec(
        s3_bucket="b", s3_region="r", s3_prefix="p", runtime="docker-local")})
    from workspace_service.auth import make_current_user_dep

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: str = Depends(make_current_user_dep(cfg))):
        return {"user": user}

    client = TestClient(app)
    resp = client.get("/whoami", headers={"X-User-Id": "bogus"})
    assert resp.status_code == 403


def test_known_user_returns_id():
    cfg = WorkspacesConfig(users={"chris": UserSpec(
        s3_bucket="b", s3_region="r", s3_prefix="p", runtime="docker-local")})
    from workspace_service.auth import make_current_user_dep

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: str = Depends(make_current_user_dep(cfg))):
        return {"user": user}

    client = TestClient(app)
    resp = client.get("/whoami", headers={"X-User-Id": "chris"})
    assert resp.status_code == 200
    assert resp.json() == {"user": "chris"}
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_auth.py -v
```

- [ ] **Step 3: Write `auth.py`**

```python
from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException, status

from workspace_service.config import WorkspacesConfig


def make_current_user_dep(config: WorkspacesConfig) -> Callable[..., str]:
    def _dep(x_user_id: str | None = Header(default=None)) -> str:
        if not x_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="X-User-Id header required")
        if x_user_id not in config.users:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="unknown user")
        return x_user_id
    return _dep
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_auth.py -v
```

- [ ] **Step 5: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/auth.py \
        experiments/vfs-workspace/service/tests/test_auth.py
git commit -m "feat(auth): X-User-Id header dependency (Phase 0 placeholder)"
```

---

## Task 11: WorkspaceManager — per-user Mirage workspace lifecycle

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/workspaces.py`
- Create: `experiments/vfs-workspace/service/tests/test_workspaces.py`

**Interfaces:**
- Consumes: `WorkspacesConfig`, `UserSpec`, runtime adapter classes.
- Produces:
  - `class WorkspaceManager`:
    - `__init__(config: WorkspacesConfig)`
    - `get_or_open(user_id: str) -> Workspace`
    - `open(user_id: str) -> Workspace`
    - `close(user_id: str) -> None`
    - `close_all() -> None`
    - `runtime_for(user_id: str) -> str` (returns runtime name)
    - Touches `last_touched[user_id]` on every `get_or_open`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_workspaces.py
from unittest.mock import MagicMock, patch

import pytest

from workspace_service.config import WorkspacesConfig, UserSpec
from workspace_service.workspaces import WorkspaceManager


@pytest.fixture
def cfg():
    return WorkspacesConfig(users={
        "chris": UserSpec(s3_bucket="b", s3_region="r", s3_prefix="p",
                          runtime="docker-local"),
    })


def test_get_or_open_caches(cfg):
    with patch("workspace_service.workspaces._build_workspace") as build:
        ws = MagicMock()
        build.return_value = ws
        mgr = WorkspaceManager(cfg)

        w1 = mgr.get_or_open("chris")
        w2 = mgr.get_or_open("chris")

        assert w1 is w2
        build.assert_called_once()


def test_close_removes_from_cache(cfg):
    with patch("workspace_service.workspaces._build_workspace") as build:
        ws = MagicMock()
        build.return_value = ws
        mgr = WorkspaceManager(cfg)

        mgr.get_or_open("chris")
        mgr.close("chris")

        ws.close.assert_called_once()
        mgr.get_or_open("chris")
        assert build.call_count == 2


def test_unknown_user_raises(cfg):
    mgr = WorkspaceManager(cfg)
    with pytest.raises(KeyError):
        mgr.get_or_open("bogus")
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_workspaces.py -v
```

- [ ] **Step 3: Write `workspaces.py`**

```python
from __future__ import annotations

import asyncio
import logging
import time

from mirage import MountMode, Workspace
from mirage.cache.file.config import CacheConfig
from mirage.cache.index.config import IndexConfig
from mirage.resource.s3 import S3Config, S3Resource
from mirage.types import CacheType, IndexType

from workspace_service.config import UserSpec, WorkspacesConfig

log = logging.getLogger(__name__)


def _build_workspace(user: UserSpec, runtime_specs: dict) -> Workspace:
    resource = S3Resource(S3Config(
        bucket=user.s3_bucket, region=user.s3_region, key_prefix=user.s3_prefix,
    ))
    runtime = _build_runtime(user.runtime, user, runtime_specs.get(user.runtime, {}))
    ws = Workspace(
        {f"/{user.mount_name.strip('/')}": resource},
        mode=MountMode.WRITE,
        cache=CacheConfig(type=CacheType.RAM, limit="512MB"),
        index=IndexConfig(type=IndexType.RAM, ttl=600),
        runtimes=[runtime],
    )
    return ws


def _build_runtime(name: str, user: UserSpec, runtime_spec: dict):
    if name == "docker-local":
        from mirage_runtimes.docker_local import DockerLocalConfig, MountLocalPython
        cfg = DockerLocalConfig(
            s3_bucket=user.s3_bucket, s3_prefix=user.s3_prefix,
            image=runtime_spec.get("image", "mirage-runtime:latest"),
            aws_env_forwarding=runtime_spec.get("aws_env_forwarding", True),
        )
        return MountLocalPython(config=cfg)
    if name == "code-interpreter":
        from mirage_runtimes.code_interpreter import CodeInterpreterConfig, CodeInterpreterPython
        cfg = CodeInterpreterConfig(
            region=runtime_spec.get("agentcore_region", user.s3_region),
            s3_bucket=user.s3_bucket,
            s3_prefix=user.s3_prefix,
            session_timeout_seconds=runtime_spec.get("session_timeout_seconds", 900),
        )
        return CodeInterpreterPython(config=cfg)
    raise ValueError(f"unknown runtime: {name}")


class WorkspaceManager:
    def __init__(self, config: WorkspacesConfig) -> None:
        self._config = config
        self._workspaces: dict[str, Workspace] = {}
        self._last_touched: dict[str, float] = {}

    def get_or_open(self, user_id: str) -> Workspace:
        if user_id not in self._config.users:
            raise KeyError(user_id)
        ws = self._workspaces.get(user_id)
        if ws is None:
            ws = _build_workspace(self._config.users[user_id], self._config.runtimes)
            self._workspaces[user_id] = ws
        self._last_touched[user_id] = time.monotonic()
        return ws

    def open(self, user_id: str) -> Workspace:
        return self.get_or_open(user_id)

    def close(self, user_id: str) -> None:
        ws = self._workspaces.pop(user_id, None)
        self._last_touched.pop(user_id, None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                log.exception("workspace close failed for %s", user_id)

    def close_all(self) -> None:
        for user_id in list(self._workspaces):
            self.close(user_id)

    def runtime_for(self, user_id: str) -> str:
        return self._config.users[user_id].runtime

    async def close_idle_task(self, idle_seconds: float = 900, poll_seconds: float = 60) -> None:
        while True:
            await asyncio.sleep(poll_seconds)
            cutoff = time.monotonic() - idle_seconds
            for user_id, last in list(self._last_touched.items()):
                if last < cutoff:
                    log.info("closing idle workspace: %s", user_id)
                    self.close(user_id)
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_workspaces.py -v
```

- [ ] **Step 5: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/workspaces.py \
        experiments/vfs-workspace/service/tests/test_workspaces.py
git commit -m "feat(workspaces): WorkspaceManager per-user Mirage lifecycle cache"
```

---

## Task 12: FastAPI app + `/health` + `/workspaces` + open/close

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/main.py`
- Create: `experiments/vfs-workspace/service/src/workspace_service/rest/__init__.py`
- Create: `experiments/vfs-workspace/service/src/workspace_service/rest/workspaces.py`
- Create: `experiments/vfs-workspace/service/tests/test_rest_workspaces.py`

**Interfaces:**
- Consumes: `WorkspacesConfig`, `WorkspaceManager`, `make_current_user_dep`.
- Produces:
  - `app: FastAPI` in `main.py`, config path from env `WORKSPACES_YAML` (default `./workspaces.yaml`).
  - Endpoints:
    - `GET /health` → `{"status": "ok"}`.
    - `GET /workspaces` → `[{"id": "chris", "runtime": "docker-local"}]` — filtered to auth'd user.
    - `POST /workspaces/{id}/open` → `{"status": "open", "runtime": "docker-local"}`, 403 if `id != user_id`.
    - `POST /workspaces/{id}/close` → `{"status": "closed"}`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_rest_workspaces.py
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    yaml_path = tmp_path / "workspaces.yaml"
    yaml_path.write_text(textwrap.dedent("""
        users:
          chris:
            s3_bucket: b
            s3_region: r
            s3_prefix: p
            runtime: docker-local
    """).strip())
    monkeypatch.setenv("WORKSPACES_YAML", str(yaml_path))

    # Patch workspace construction so tests don't try to start docker.
    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod, "_build_workspace", lambda user, specs: object())

    from workspace_service.main import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_workspaces_lists_only_own(client):
    r = client.get("/workspaces", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert r.json() == [{"id": "chris", "runtime": "docker-local"}]


def test_open_own_workspace(client):
    r = client.post("/workspaces/chris/open", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert r.json()["runtime"] == "docker-local"


def test_open_other_workspace_forbidden(client):
    r = client.post("/workspaces/other/open", headers={"X-User-Id": "chris"})
    assert r.status_code in (403, 404)


def test_close_workspace(client):
    client.post("/workspaces/chris/open", headers={"X-User-Id": "chris"})
    r = client.post("/workspaces/chris/close", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_rest_workspaces.py -v
```

- [ ] **Step 3: Write `rest/workspaces.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from workspace_service.workspaces import WorkspaceManager


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["workspaces"])

    @router.get("")
    def list_workspaces(user: str = Depends(current_user_dep)):
        # One workspace per user in Phase 0 — return the user's own.
        return [{"id": user, "runtime": manager.runtime_for(user)}]

    @router.post("/{workspace_id}/open")
    def open_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(status_code=403, detail="not your workspace")
        manager.get_or_open(user)
        return {"status": "open", "runtime": manager.runtime_for(user)}

    @router.post("/{workspace_id}/close")
    def close_ws(workspace_id: str, user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(status_code=403, detail="not your workspace")
        manager.close(user)
        return {"status": "closed"}

    return router
```

- [ ] **Step 4: Write `main.py`**

```python
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from workspace_service.auth import make_current_user_dep
from workspace_service.config import load_config
from workspace_service.rest.workspaces import build_router as build_workspaces_router
from workspace_service.workspaces import WorkspaceManager


def create_app() -> FastAPI:
    config_path = Path(os.environ.get("WORKSPACES_YAML", "./workspaces.yaml"))
    config = load_config(config_path)
    manager = WorkspaceManager(config)
    current_user_dep = make_current_user_dep(config)

    app = FastAPI(title="vfs-workspace service")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(build_workspaces_router(manager, current_user_dep))

    app.state.manager = manager
    app.state.config = config

    @app.on_event("shutdown")
    def _shutdown():
        manager.close_all()

    return app


app = create_app()
```

Also `rest/__init__.py` empty.

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_rest_workspaces.py -v
```

- [ ] **Step 6: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/main.py \
        experiments/vfs-workspace/service/src/workspace_service/rest/ \
        experiments/vfs-workspace/service/tests/test_rest_workspaces.py
git commit -m "feat(rest): FastAPI app + /health + /workspaces + open/close"
```

---

## Task 13: REST — file tree + read + write + delete

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/rest/files.py`
- Modify: `experiments/vfs-workspace/service/src/workspace_service/main.py` (register router)
- Create: `experiments/vfs-workspace/service/tests/test_rest_files.py`

**Interfaces:**
- Consumes: `WorkspaceManager` (`get_or_open` returns Mirage `Workspace`).
- Produces:
  - `GET /workspaces/{id}/tree?path=&depth=` → `{"entries": [{"path": "...", "is_dir": bool, "size": int|null}, ...]}`.
  - `GET /workspaces/{id}/files/{path:path}` → file bytes (Content-Type sniffed to `text/plain; charset=utf-8` when decodable, else `application/octet-stream`).
  - `PUT /workspaces/{id}/files/{path:path}` → 204, body raw bytes.
  - `DELETE /workspaces/{id}/files/{path:path}` → 204.

- [ ] **Step 1: Write failing tests (workspace ops mocked)**

```python
# tests/test_rest_files.py
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock


class FakeIO:
    def __init__(self):
        self.files = {"/disk/hello.txt": b"hello"}

    def readdir(self, path):
        # returns list of paths under this dir
        entries = [p for p in self.files if p.startswith(path.rstrip("/") + "/")]
        return entries

    def cat(self, path):
        data = self.files.get(path)
        if data is None:
            return (1, b"", b"no such file")
        return (0, data, b"")

    def tee(self, path, data):
        self.files[path] = data
        return (0, b"", b"")

    def rm(self, path):
        self.files.pop(path, None)
        return (0, b"", b"")


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(textwrap.dedent("""
        users:
          chris:
            s3_bucket: b
            s3_region: r
            s3_prefix: p
            runtime: docker-local
    """).strip())
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    fake_ws = MagicMock()
    fake_ws.io = FakeIO()

    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod, "_build_workspace", lambda user, specs: fake_ws)

    from workspace_service.main import create_app
    return TestClient(create_app())


def test_tree_lists_entries(client):
    r = client.get("/workspaces/chris/tree?path=/disk", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    body = r.json()
    assert any(e["path"].endswith("hello.txt") for e in body["entries"])


def test_read_file(client):
    r = client.get("/workspaces/chris/files/hello.txt", headers={"X-User-Id": "chris"})
    assert r.status_code == 200
    assert r.text == "hello"


def test_write_then_read(client):
    r = client.put(
        "/workspaces/chris/files/new.txt",
        content=b"world",
        headers={"X-User-Id": "chris", "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 204
    r2 = client.get("/workspaces/chris/files/new.txt", headers={"X-User-Id": "chris"})
    assert r2.text == "world"


def test_delete(client):
    client.put("/workspaces/chris/files/gone.txt", content=b"x",
               headers={"X-User-Id": "chris"})
    r = client.delete("/workspaces/chris/files/gone.txt",
                      headers={"X-User-Id": "chris"})
    assert r.status_code == 204
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Write `rest/files.py`**

Adapter over Mirage `Workspace.io`. Real mirage `io` methods are async and return dispatch tuples; adapt via a small helper. For the mocked tests above, the endpoint code uses `ws.io.readdir(path)`, `ws.io.cat(path)`, `ws.io.tee(path, bytes)`, `ws.io.rm(path)` — all synchronous in the fake. Production code awaits mirage's async equivalents.

Reference `experiments/deepagents-repl/runtime/_mirage_io.py` for the real async wiring pattern — port that helper class into `workspace_service/rest/files.py` as `_WsIO`, keyed to the mount name from `UserSpec.mount_name`.

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Request

from workspace_service.workspaces import WorkspaceManager


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["files"])

    def _mount_path(user: str, virtual: str) -> str:
        cfg = manager._config.users[user]  # noqa: SLF001 - internal read
        base = f"/{cfg.mount_name.strip('/')}"
        v = "/" + virtual.lstrip("/")
        return f"{base}{v}" if v != "/" else base

    @router.get("/{workspace_id}/tree")
    def tree(workspace_id: str, path: str = "/", depth: int = 2,
             user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        ws = manager.get_or_open(user)
        base = _mount_path(user, path)
        entries = ws.io.readdir(base)
        # Normalize: return virtual paths (strip mount prefix)
        prefix = f"/{manager._config.users[user].mount_name.strip('/')}"
        out = []
        for p in entries:
            virtual = p[len(prefix):] or "/"
            out.append({"path": virtual, "is_dir": p.endswith("/"), "size": None})
        return {"entries": out}

    @router.get("/{workspace_id}/files/{file_path:path}")
    def read(workspace_id: str, file_path: str,
             user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        ws = manager.get_or_open(user)
        rc, data, err = ws.io.cat(_mount_path(user, file_path))
        if rc != 0:
            raise HTTPException(404, err.decode(errors="replace") or "not found")
        try:
            text = data.decode("utf-8")
            return Response(content=text, media_type="text/plain; charset=utf-8")
        except UnicodeDecodeError:
            return Response(content=data, media_type="application/octet-stream")

    @router.put("/{workspace_id}/files/{file_path:path}", status_code=204)
    async def write(workspace_id: str, file_path: str, request: Request,
                    user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        ws = manager.get_or_open(user)
        body = await request.body()
        rc, _, err = ws.io.tee(_mount_path(user, file_path), body)
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "write failed")
        return Response(status_code=204)

    @router.delete("/{workspace_id}/files/{file_path:path}", status_code=204)
    def delete(workspace_id: str, file_path: str,
               user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        ws = manager.get_or_open(user)
        rc, _, err = ws.io.rm(_mount_path(user, file_path))
        if rc != 0:
            raise HTTPException(500, err.decode(errors="replace") or "delete failed")
        return Response(status_code=204)

    return router
```

**Note for the executor:** the real mirage `Workspace.io` API is async and returns richer types than the fake above. When wiring against real mirage, port the `MirageIO` helper from `experiments/deepagents-repl/runtime/_mirage_io.py` (uses an `AsyncLoop`) into this router or a service-level helper, and switch these handlers to `async def` awaiting the helper. The mocked-workspace tests above lock the router's HTTP contract — they should keep passing while you swap the internals.

- [ ] **Step 4: Register router in `main.py`**

Add:
```python
from workspace_service.rest.files import build_router as build_files_router
...
app.include_router(build_files_router(manager, current_user_dep))
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_rest_files.py -v
```

- [ ] **Step 6: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/rest/files.py \
        experiments/vfs-workspace/service/src/workspace_service/main.py \
        experiments/vfs-workspace/service/tests/test_rest_files.py
git commit -m "feat(rest): file tree + read/write/delete endpoints"
```

---

## Task 14: REST — `POST /exec`

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/rest/exec.py`
- Modify: `experiments/vfs-workspace/service/src/workspace_service/main.py`
- Create: `experiments/vfs-workspace/service/tests/test_rest_exec.py`

**Interfaces:**
- Consumes: `WorkspaceManager`, mirage `Workspace.execute` (or equivalent).
- Produces:
  - `POST /workspaces/{id}/exec` body `{"language": "python"|"node", "code": str, "args": [str] = [], "stdin": str = "", "env": {} = {}, "timeout": float | null = null}`.
  - Response `{"stdout": str, "stderr": str, "exit_code": int, "elapsed_ms": int}`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_rest_exec.py
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(textwrap.dedent("""
        users:
          chris:
            s3_bucket: b
            s3_region: r
            s3_prefix: p
            runtime: docker-local
    """).strip())
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    fake_ws = MagicMock()

    async def fake_exec(cmd, **kwargs):
        # Emulate mirage's ws.execute return shape (adjust to real one).
        m = MagicMock()
        m.stdout = b"hi\n"
        m.stderr = b""
        m.exit_code = 0
        return m

    fake_ws.execute = fake_exec
    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod, "_build_workspace", lambda user, specs: fake_ws)

    from workspace_service.main import create_app
    return TestClient(create_app())


def test_exec_python(client):
    r = client.post(
        "/workspaces/chris/exec",
        json={"language": "python", "code": "print('hi')"},
        headers={"X-User-Id": "chris"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 0
    assert "hi" in body["stdout"]


def test_exec_unknown_language(client):
    r = client.post(
        "/workspaces/chris/exec",
        json={"language": "rust", "code": "fn main(){}"},
        headers={"X-User-Id": "chris"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Write `rest/exec.py`**

```python
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from workspace_service.workspaces import WorkspaceManager


class ExecRequest(BaseModel):
    language: Literal["python", "node"]
    code: str
    args: list[str] = Field(default_factory=list)
    stdin: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int


_INTERPRETER_MAP = {"python": "python3", "node": "node"}


def build_router(manager: WorkspaceManager, current_user_dep) -> APIRouter:
    router = APIRouter(prefix="/workspaces", tags=["exec"])

    @router.post("/{workspace_id}/exec", response_model=ExecResponse)
    async def exec_code(workspace_id: str, req: ExecRequest,
                        user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        interpreter = _INTERPRETER_MAP.get(req.language)
        if interpreter is None:
            raise HTTPException(400, f"unsupported language: {req.language}")

        ws = manager.get_or_open(user)
        started = time.monotonic()
        # NOTE: real mirage ws.execute API to be verified during
        # implementation; here we assume it accepts a shell-like command.
        # If it needs a RunArgs directly, wire through workspace's
        # command routing instead.
        cmd = f"{interpreter} -c {_shq(req.code)}"
        result = await ws.execute(cmd, timeout=req.timeout)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ExecResponse(
            stdout=_to_str(result.stdout),
            stderr=_to_str(result.stderr) if result.stderr else "",
            exit_code=int(result.exit_code),
            elapsed_ms=elapsed_ms,
        )

    return router


def _to_str(v) -> str:
    if v is None: return ""
    if isinstance(v, bytes): return v.decode("utf-8", errors="replace")
    return str(v)


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
```

**Note for the executor:** verify `ws.execute` signature and return shape when integrating against real mirage. Adjust `cmd` construction accordingly — many `Workspace.execute` implementations take structured args instead of a shell string.

- [ ] **Step 4: Register in `main.py`**

```python
from workspace_service.rest.exec import build_router as build_exec_router
...
app.include_router(build_exec_router(manager, current_user_dep))
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_rest_exec.py -v
```

- [ ] **Step 6: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/rest/exec.py \
        experiments/vfs-workspace/service/src/workspace_service/main.py \
        experiments/vfs-workspace/service/tests/test_rest_exec.py
git commit -m "feat(rest): POST /exec routes python/node through workspace runtime"
```

---

## Task 15: MCP HTTP surface — per-workspace endpoint

**Files:**
- Create: `experiments/vfs-workspace/service/src/workspace_service/mcp/__init__.py`
- Create: `experiments/vfs-workspace/service/src/workspace_service/mcp/server.py`
- Modify: `experiments/vfs-workspace/service/src/workspace_service/main.py`
- Create: `experiments/vfs-workspace/service/tests/test_mcp.py`

**Interfaces:**
- Consumes: `WorkspaceManager`, mirage tool definitions from `mirage.agents.claude_agent_sdk.server`.
- Produces:
  - `build_mcp_app(manager: WorkspaceManager, current_user_dep) -> ASGI app` — FastMCP HTTP app mounted under `/mcp/workspaces/{id}`.
  - Tools mirror mirage's built-in set: `read`, `write`, `edit`, `grep`, `glob`, `ls`, `delete`, `execute`.

- [ ] **Step 1: Read the mirage tool set to reuse shapes**

```bash
uv run python -c "from mirage.agents.claude_agent_sdk import server as s; print(dir(s))"
uv run python -c "from mirage.agents.claude_agent_sdk.server import _MirageTools; print(_MirageTools.__dict__)"
```
Record tool names + arg shapes. If reusable, wrap them; if internal-only, port their surface into our FastMCP tools.

- [ ] **Step 2: Write failing test — MCP `tools/list` returns expected names**

```python
# tests/test_mcp.py
import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    (tmp_path / "workspaces.yaml").write_text(textwrap.dedent("""
        users:
          chris:
            s3_bucket: b
            s3_region: r
            s3_prefix: p
            runtime: docker-local
    """).strip())
    monkeypatch.setenv("WORKSPACES_YAML", str(tmp_path / "workspaces.yaml"))

    fake_ws = MagicMock()
    from workspace_service import workspaces as ws_mod
    monkeypatch.setattr(ws_mod, "_build_workspace", lambda user, specs: fake_ws)

    from workspace_service.main import create_app
    return TestClient(create_app())


def test_mcp_tools_list(client):
    # FastMCP HTTP responds to JSON-RPC style POST at /mcp
    r = client.post(
        "/mcp/workspaces/chris",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"X-User-Id": "chris", "Accept": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    tool_names = {t["name"] for t in body["result"]["tools"]}
    for expected in ("read", "write", "edit", "grep", "ls", "delete", "execute"):
        assert expected in tool_names
```

- [ ] **Step 3: Run — expect FAIL**

- [ ] **Step 4: Write `mcp/server.py`**

Wrap mirage's tool set via FastMCP HTTP. The exact FastMCP wiring depends on its version; below is the intent — adjust to the real API surface:

```python
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastmcp import FastMCP

from workspace_service.workspaces import WorkspaceManager


def build_mcp(manager: WorkspaceManager, workspace_id: str) -> FastMCP:
    """One FastMCP instance per open workspace, bound to that workspace."""
    ws = manager.get_or_open(workspace_id)
    mcp = FastMCP(f"vfs-workspace-{workspace_id}")

    @mcp.tool
    def read(file_path: str, offset: int = 0, limit: int = 2000) -> dict:
        rc, data, err = ws.io.cat(_mount_path(manager, workspace_id, file_path))
        if rc != 0:
            return {"error": err.decode(errors="replace") or "not found"}
        try:
            text = data.decode("utf-8")
            lines = text.splitlines()
            return {"content": "\n".join(lines[offset:offset + limit])}
        except UnicodeDecodeError:
            return {"file_data": {"encoding": "base64",
                                  "content": _b64(data)}}

    @mcp.tool
    def write(file_path: str, content: str) -> dict:
        rc, _, err = ws.io.tee(_mount_path(manager, workspace_id, file_path),
                               content.encode("utf-8"))
        if rc != 0:
            return {"error": err.decode(errors="replace")}
        return {"path": file_path}

    @mcp.tool
    def ls(path: str = "/") -> dict:
        entries = ws.io.readdir(_mount_path(manager, workspace_id, path))
        return {"entries": [{"path": p, "is_dir": p.endswith("/")} for p in entries]}

    @mcp.tool
    def delete(file_path: str) -> dict:
        rc, _, err = ws.io.rm(_mount_path(manager, workspace_id, file_path))
        if rc != 0:
            return {"error": err.decode(errors="replace")}
        return {"path": file_path}

    @mcp.tool
    def execute(command: str, timeout: float | None = None) -> dict:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            ws.execute(command, timeout=timeout)
        )
        return {
            "stdout": _b(result.stdout).decode(errors="replace"),
            "stderr": (_b(result.stderr) or b"").decode(errors="replace"),
            "exit_code": int(result.exit_code),
        }

    # TODO(executor): grep, glob, edit — same pattern. Port shapes from
    # mirage.agents.claude_agent_sdk.server._MirageTools if signatures match.

    return mcp


def mount_mcp_routes(app, manager: WorkspaceManager, current_user_dep):
    """Mount /mcp/workspaces/{id} sub-apps on-demand."""
    from fastapi import Depends, Request

    @app.post("/mcp/workspaces/{workspace_id}")
    async def mcp_endpoint(workspace_id: str, request: Request,
                           user: str = Depends(current_user_dep)):
        if workspace_id != user:
            raise HTTPException(403, "not your workspace")
        mcp = build_mcp(manager, workspace_id)
        # FastMCP HTTP transport wants to handle raw JSON-RPC frames.
        payload = await request.json()
        return await mcp.handle_http(payload)


def _mount_path(manager: WorkspaceManager, user: str, virtual: str) -> str:
    base = f"/{manager._config.users[user].mount_name.strip('/')}"  # noqa: SLF001
    v = "/" + virtual.lstrip("/")
    return f"{base}{v}" if v != "/" else base


def _b(x) -> bytes:
    if isinstance(x, bytes): return x
    if x is None: return b""
    return str(x).encode()


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode()
```

- [ ] **Step 5: Wire MCP mount in `main.py`**

```python
from workspace_service.mcp.server import mount_mcp_routes
...
mount_mcp_routes(app, manager, current_user_dep)
```

- [ ] **Step 6: Run — verify test passes**

Real FastMCP JSON-RPC transport wiring may differ. If FastMCP doesn't ship a `handle_http` method, use its `Server.dispatch()` or `to_asgi()` API instead. Verify by:

```bash
uv run python -c "from fastmcp import FastMCP; m = FastMCP('x'); print([a for a in dir(m) if not a.startswith('_')])"
```

Iterate on `mount_mcp_routes` until `test_mcp_tools_list` passes.

- [ ] **Step 7: Commit**

```bash
git add experiments/vfs-workspace/service/src/workspace_service/mcp/ \
        experiments/vfs-workspace/service/src/workspace_service/main.py \
        experiments/vfs-workspace/service/tests/test_mcp.py
git commit -m "feat(mcp): per-workspace HTTP MCP endpoint at /mcp/workspaces/{id}"
```

---

## Task 16: UI scaffold — SvelteKit + shadcn-svelte + Tailwind + API client

**Files:**
- Create: everything under `experiments/vfs-workspace/ui/` via scaffolds.

**Interfaces:**
- Consumes: workspace service REST (`GET /workspaces`, `POST /open`, `GET /tree`, `GET /files/{p}`, `POST /exec`).
- Produces: dev-server-runnable SvelteKit app at http://localhost:5173 in dev.

- [ ] **Step 1: Scaffold SvelteKit + Tailwind**

```bash
cd experiments/vfs-workspace/ui
pnpm create svelte@latest . --template skeleton --types typescript --no-add-ons
pnpm install
pnpm add -D tailwindcss@next @tailwindcss/vite@next
pnpm add -D bits-ui   # shadcn-svelte's headless component base
```

Configure Tailwind 4 per its Vite plugin instructions (add `@tailwindcss/vite` to `vite.config.ts`, `@import "tailwindcss";` to `src/app.css`).

- [ ] **Step 2: Add shadcn-svelte components used by Phase 0**

```bash
pnpm dlx shadcn-svelte@latest init
pnpm dlx shadcn-svelte@latest add button input textarea select card badge separator
```

Answer prompts choosing Tailwind 4, default paths.

- [ ] **Step 3: Write `src/lib/api.ts` — typed REST client**

```ts
const BASE = import.meta.env.PUBLIC_API_BASE ?? "http://localhost:8000";
const USER = import.meta.env.PUBLIC_USER_ID ?? "chris";

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "X-User-Id": USER, ...(init.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get("content-type") ?? "";
  return ct.includes("application/json") ? res.json() : (res.text() as any);
}

export type Workspace = { id: string; runtime: string };
export type TreeEntry = { path: string; is_dir: boolean; size: number | null };
export type ExecResp = { stdout: string; stderr: string; exit_code: number; elapsed_ms: number };

export const api = {
  listWorkspaces: () => req<Workspace[]>("/workspaces"),
  openWorkspace: (id: string) => req<{ status: string; runtime: string }>(
    `/workspaces/${id}/open`, { method: "POST" }),
  tree: (id: string, path = "/") => req<{ entries: TreeEntry[] }>(
    `/workspaces/${id}/tree?path=${encodeURIComponent(path)}`),
  readFile: (id: string, path: string) => req<string>(
    `/workspaces/${id}/files/${path.replace(/^\//, "")}`),
  exec: (id: string, body: { language: "python" | "node"; code: string }) =>
    req<ExecResp>(`/workspaces/${id}/exec`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
```

- [ ] **Step 4: Commit scaffold**

```bash
git add experiments/vfs-workspace/ui/
git commit -m "feat(ui): SvelteKit + Tailwind + shadcn-svelte scaffold + API client"
```

---

## Task 17: UI — workspace list page

**Files:**
- Create: `experiments/vfs-workspace/ui/src/routes/+layout.svelte`
- Create: `experiments/vfs-workspace/ui/src/routes/+page.svelte`

**Interfaces:**
- Consumes: `api.listWorkspaces()`.
- Produces: `/` renders one card per workspace with runtime badge; click navigates to `/w/{id}`.

- [ ] **Step 1: Write `+layout.svelte`**

```svelte
<script lang="ts">
  import "../app.css";
  let { children } = $props();
</script>

<div class="min-h-screen bg-background text-foreground">
  <header class="border-b p-4 font-mono text-sm">vfs-workspace</header>
  <main class="p-4">
    {@render children()}
  </main>
</div>
```

- [ ] **Step 2: Write `routes/+page.svelte`**

```svelte
<script lang="ts">
  import { api, type Workspace } from "$lib/api";
  import { Card, CardHeader, CardTitle, CardContent } from "$lib/components/ui/card";
  import { Badge } from "$lib/components/ui/badge";

  let workspaces = $state<Workspace[]>([]);
  let error = $state<string | null>(null);

  $effect(() => {
    api.listWorkspaces().then(w => workspaces = w).catch(e => error = String(e));
  });
</script>

<h1 class="text-lg mb-4">Workspaces</h1>

{#if error}
  <div class="text-red-500">{error}</div>
{/if}

<div class="grid gap-3 grid-cols-1 md:grid-cols-3">
  {#each workspaces as ws}
    <a href={`/w/${ws.id}`}>
      <Card>
        <CardHeader>
          <CardTitle>{ws.id}</CardTitle>
        </CardHeader>
        <CardContent>
          <Badge variant="secondary">{ws.runtime}</Badge>
        </CardContent>
      </Card>
    </a>
  {/each}
</div>
```

- [ ] **Step 3: Manual visual check**

```bash
cd experiments/vfs-workspace/ui && pnpm dev
```
Visit http://localhost:5173. With the service running, expect a card for the configured user.

- [ ] **Step 4: Commit**

```bash
git add experiments/vfs-workspace/ui/src/routes/
git commit -m "feat(ui): workspace list page"
```

---

## Task 18: UI — workspace view (`/w/{id}`) — three panes

**Files:**
- Create: `experiments/vfs-workspace/ui/src/routes/w/[id]/+page.svelte`
- Create: `experiments/vfs-workspace/ui/src/lib/components/FileTree.svelte`
- Create: `experiments/vfs-workspace/ui/src/lib/components/ExecPane.svelte`

**Interfaces:**
- Consumes: `api.openWorkspace()`, `api.tree()`, `api.readFile()`, `api.exec()`.
- Produces: three-pane layout — tree (left), preview (middle), exec (right).

- [ ] **Step 1: Write `FileTree.svelte`**

```svelte
<script lang="ts">
  import { api, type TreeEntry } from "$lib/api";

  let { workspaceId, onSelect } = $props<{
    workspaceId: string;
    onSelect: (path: string) => void;
  }>();

  let entries = $state<TreeEntry[]>([]);

  $effect(() => {
    api.tree(workspaceId).then(t => entries = t.entries).catch(() => entries = []);
  });
</script>

<ul class="font-mono text-sm space-y-1">
  {#each entries as e}
    <li>
      {#if e.is_dir}
        <span class="opacity-70">📁 {e.path}</span>
      {:else}
        <button class="underline hover:opacity-70" onclick={() => onSelect(e.path)}>
          📄 {e.path}
        </button>
      {/if}
    </li>
  {/each}
</ul>
```

- [ ] **Step 2: Write `ExecPane.svelte`**

```svelte
<script lang="ts">
  import { api, type ExecResp } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";

  let { workspaceId, runtime } = $props<{
    workspaceId: string;
    runtime: string;
  }>();

  let language = $state<"python" | "node">("python");
  let code = $state("print('hello')");
  let result = $state<ExecResp | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  const nodeDisabled = runtime === "code-interpreter";

  async function run() {
    busy = true; error = null;
    try {
      result = await api.exec(workspaceId, { language, code });
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="space-y-3">
  <div class="flex gap-2">
    <select bind:value={language} class="border rounded px-2 py-1 text-sm">
      <option value="python">Python</option>
      <option value="node" disabled={nodeDisabled}>Node {nodeDisabled ? "(N/A)" : ""}</option>
    </select>
    <Button onclick={run} disabled={busy}>{busy ? "Running..." : "Run"}</Button>
  </div>

  <Textarea rows={12} bind:value={code} class="font-mono text-xs" />

  {#if error}
    <div class="text-red-500 text-xs">{error}</div>
  {/if}

  {#if result}
    <div class="border rounded p-2 text-xs font-mono">
      <div class="opacity-70">exit={result.exit_code} · {result.elapsed_ms}ms</div>
      {#if result.stdout}<pre class="mt-2 whitespace-pre-wrap">{result.stdout}</pre>{/if}
      {#if result.stderr}<pre class="mt-2 whitespace-pre-wrap text-red-400">{result.stderr}</pre>{/if}
    </div>
  {/if}
</div>
```

- [ ] **Step 3: Write `routes/w/[id]/+page.svelte`**

```svelte
<script lang="ts">
  import { page } from "$app/state";
  import { api } from "$lib/api";
  import FileTree from "$lib/components/FileTree.svelte";
  import ExecPane from "$lib/components/ExecPane.svelte";
  import { Badge } from "$lib/components/ui/badge";

  const id = $derived(page.params.id);

  let runtime = $state<string | null>(null);
  let selectedPath = $state<string | null>(null);
  let preview = $state<string | null>(null);

  $effect(() => {
    api.openWorkspace(id).then(r => runtime = r.runtime).catch(() => runtime = null);
  });

  $effect(() => {
    if (selectedPath) api.readFile(id, selectedPath).then(t => preview = t);
  });
</script>

<div class="flex items-center gap-2 mb-4">
  <h1 class="text-lg">{id}</h1>
  {#if runtime}<Badge variant="secondary">{runtime}</Badge>{/if}
</div>

<div class="grid grid-cols-12 gap-4">
  <aside class="col-span-3 border rounded p-3">
    <FileTree workspaceId={id} onSelect={(p) => selectedPath = p} />
  </aside>
  <section class="col-span-5 border rounded p-3">
    {#if preview !== null}
      <pre class="font-mono text-xs whitespace-pre-wrap">{preview}</pre>
    {:else}
      <div class="opacity-50 text-sm">Select a file</div>
    {/if}
  </section>
  <section class="col-span-4 border rounded p-3">
    {#if runtime}
      <ExecPane workspaceId={id} {runtime} />
    {/if}
  </section>
</div>
```

- [ ] **Step 4: Manual smoke test**

Start service + UI, navigate to `/w/chris`, verify tree renders, file preview loads on click, exec pane runs code and returns output.

- [ ] **Step 5: Commit**

```bash
git add experiments/vfs-workspace/ui/src/
git commit -m "feat(ui): workspace view — tree + preview + exec panes"
```

---

## Task 19: End-to-end smoke test

**Files:**
- None created; verifies success criteria from spec Section 14.

**Interfaces:**
- Consumes: everything.
- Produces: pass/fail signal against spec success criteria.

- [ ] **Step 1: Verify per-experiment installs**

```bash
for d in experiments/*/; do
  if [ -f "$d/pyproject.toml" ]; then
    echo "=== $d ==="
    (cd "$d" && uv sync)
  fi
done
```
Each `uv sync` returns 0.

- [ ] **Step 2: Verify service starts and health responds**

```bash
cd experiments/vfs-workspace/service
cp workspaces.yaml.example workspaces.yaml   # edit S3 bucket/prefix first
uv run uvicorn workspace_service.main:app --port 8000 &
SVC_PID=$!
sleep 3
curl -sf http://localhost:8000/health
kill $SVC_PID
```

- [ ] **Step 3: Verify `docker-local` end-to-end**

Assumes runtime image is built (Task 5). AWS creds exported. `workspaces.yaml` has a `docker-local` user pointing at a real S3 prefix.

```bash
uv run uvicorn workspace_service.main:app --port 8000 &
sleep 3
curl -sf -H "X-User-Id: chris" http://localhost:8000/workspaces
curl -sf -H "X-User-Id: chris" -X POST http://localhost:8000/workspaces/chris/open
curl -sf -H "X-User-Id: chris" "http://localhost:8000/workspaces/chris/tree?path=/"
curl -sf -H "X-User-Id: chris" -X POST http://localhost:8000/workspaces/chris/exec \
  -H "Content-Type: application/json" \
  -d '{"language":"python","code":"print(\"hi\")"}'
```
Last curl returns `{"stdout":"hi\n", ...}`.

- [ ] **Step 4: Verify `code-interpreter` end-to-end** (needs Bedrock CodeInterpreter access)

Configure a second user in `workspaces.yaml` with `runtime: code-interpreter`. Repeat Step 3's curls against that user.

- [ ] **Step 5: Verify UI end-to-end**

```bash
cd experiments/vfs-workspace/ui
pnpm dev &
```
Browser: http://localhost:5173. Workspace list → click → tree renders → file preview loads → exec pane runs `print("hi")` → output shown.

- [ ] **Step 6: Verify MCP endpoint responds**

```bash
curl -sf -H "X-User-Id: chris" -H "Content-Type: application/json" \
  -X POST http://localhost:8000/mcp/workspaces/chris \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```
Returns JSON with tool list including `read`, `write`, `execute`.

- [ ] **Step 7: Verify idle sweeper**

Configure `close_idle_task` with a short timeout (30s) via env-var override or code tweak, exercise workspace once, wait 45s, verify workspace is torn down (logs show close; new request rebuilds).

- [ ] **Step 8: Commit any doc updates if smoke test surfaced fixes**

```bash
git status
# If fixes needed, apply, then:
git commit -m "fix: address smoke-test findings"
```

If no fixes: skip commit.

---

## Self-Review

**Spec coverage** — each spec section maps to a task:
- Section 3 (repo reshuffle) → Tasks 1, 2, 3
- Section 4 (vfs-workspace layout) → Task 4
- Section 5 (layered architecture) → holistic; realized by Tasks 12–15
- Section 6 (config model) → Task 9
- Section 7 (workspace lifecycle) → Task 11
- Section 8.1 (`docker-local`) → Tasks 5, 6, 7
- Section 8.2 (`code-interpreter`) → Task 8
- Section 9.1 (REST) → Tasks 12, 13, 14
- Section 9.2 (MCP) → Task 15
- Section 10 (UI) → Tasks 16, 17, 18
- Section 11 (failure modes) → surfaced in Tasks 6, 8 (raises), Task 14 (400 on unknown language)
- Section 12 (dev workflow) → Task 4 (README), Task 19 (smoke)
- Section 14 (success criteria) → Task 19

**Placeholder scan** — three "TODO / verify at implementation" callouts remain and are unavoidable at plan-time:
- Task 7 Step 5: verify actual `JsRuntime` base import path (mirage may have `JsRuntime`, `QuickJsRuntime`, or similar).
- Task 8 Step 1 + Step 6: verify boto3 `bedrock-agentcore*` client + method names against the installed boto3 version.
- Task 13 Step 3 and Task 14 Step 3: verify mirage `Workspace.io.*` and `Workspace.execute` sync/async signatures before wiring for real (tests use mocks that lock the HTTP contract).

Each is scoped to a specific step with the verification command inline. Not blocking — engineer runs the check, tunes the two-line surface, continues.

**Type consistency** — `DockerLocalConfig`, `CodeInterpreterConfig`, `UserSpec`, `WorkspacesConfig`, `WorkspaceManager`, `ExecRequest/Response` names are used consistently across tasks. Runtime name strings (`docker-local`, `code-interpreter`) match everywhere. REST paths (`/workspaces/{id}/...`) consistent. MCP mount (`/mcp/workspaces/{id}`) consistent.

**Task granularity** — largest tasks (5, 6, 8, 15, 18) each span ~5–8 steps. All have independent test cycle (`uv run pytest ...` per task) except UI tasks 17/18 which rely on manual visual check. That's expected for UI work; documented.

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-29-vfs-workspace.md`.**
