# VFS Workspace Experiment — Design

**Status:** Draft
**Date:** 2026-08-29
**Author:** Chris Owen (via brainstorm w/ Claude)
**Scope:** Phase 0 of the workspace-service track. Delivers a Mirage-backed workspace service, two Python runtime adapters (`docker-local`, `code-interpreter`), an HTTP REST + MCP surface, and a Svelte web UI for browsing files and running arbitrary code against a workspace.

Explicit non-goals: agent service, chat UI, Keycloak auth, `sync-local` adapter, multi-workspace-per-user, JS on code-interpreter, WS streaming, production deployment.

---

## 1. Motivation

Today's `experiments/vff/` prototype proves out a mirage-backed FastMCP server with a single workspace per process and a monty exec tool. It works but is single-purpose and does not exercise Mirage's own runtime plugin surface.

The goal now is a generic **virtual filesystem workspace service**:

- Read/write/edit/grep/glob/ls file operations backed by an S3 workspace (through Mirage).
- Execute Python (and later Node) code against that workspace, where the runtime is a pluggable adapter (mount-based container locally, remote AgentCore CodeInterpreter in the cloud, sync-based sandbox later).
- An HTTP REST surface for a web UI to browse files and run code.
- An HTTP MCP surface for a future agent to consume the same tools.

Mirage already provides: a `Workspace` abstraction over pluggable resource backends (S3, disk, Redis, Mongo, RAM), a per-language runtime tier (`PythonRuntime`, `JsRuntime`) with public plugin protocol, a mount/dispatch model, and a built-in in-process MCP tool set (`mirage.agents.claude_agent_sdk.server`). This experiment extends Mirage rather than reinventing it.

## 2. Scope

### In scope (Phase 0)

- Repo reshuffle: move all existing top-level projects into isolated `experiments/*` folders, each with its own `pyproject.toml` / `uv.lock` / `.venv`.
- New experiment `experiments/vfs-workspace/` containing:
  - `service/` — FastAPI Python service exposing REST + HTTP MCP.
  - `runtime-image/` — Docker base image used by the `docker-local` runtime.
  - `ui/` — SvelteKit + shadcn-svelte web UI.
- Two Python runtime adapters registered as Mirage runtimes:
  - `docker-local` (Python + Node) — long-lived container per workspace with mountpoint-s3 mount at `/workspace`.
  - `code-interpreter` (Python only) — Bedrock AgentCore CodeInterpreter session with S3 filesystem config.
- Trivial per-user config: static YAML mapping `user_id → { s3_bucket, s3_prefix, runtime, ... }`.
- Trivial auth: `X-User-Id` header. Placeholder for Keycloak.

### Out of scope (deferred to later phases)

- Agent service (separate process running Claude SDK, consuming the workspace MCP endpoint).
- Chat UI (workspace UI is browse + exec only for Phase 0).
- Keycloak OIDC, session tokens, real auth.
- `sync-local` adapter (pull/push sandbox for non-mountable sources like SharePoint or GitHub).
- Multi-workspace-per-user.
- JS runtime on `code-interpreter` (blocked on AWS Node support).
- WebSocket streaming of exec output (buffered responses only).
- File-write from UI (read-only tree/preview at MVP).
- Production deployment. Local docker-compose only.
- Observability beyond stdout logs.

Each deferred item becomes its own follow-up spec.

## 3. Repo Reshuffle

Every experiment is a self-contained project with its own dependency set. Root holds only an index and per-experiment folders. No shared `pyproject.toml`, no shared `.venv`.

### Target layout

```
agent-runtime-adapter/
├── README.md                          # index of experiments
├── .gitignore
└── experiments/
    ├── deepagents-repl/               # was: runtime/ + agent.py + workspace/
    │   ├── pyproject.toml
    │   ├── uv.lock
    │   ├── .python-version
    │   ├── runtime/
    │   ├── agent.py
    │   └── workspace/
    ├── vff/                           # existing prototype
    │   ├── pyproject.toml             # NEW — extracted from root
    │   ├── uv.lock
    │   ├── server.py
    │   └── agent.py
    ├── eks-agent/                     # was: eks/
    │   ├── pyproject.toml
    │   └── app/
    ├── agentcore-ada/                 # was: ada/
    │   ├── pyproject.toml (or none if pure infra)
    │   └── agentcore/
    └── vfs-workspace/                 # NEW — this design
        └── (see Section 4)
```

### Sequencing

1. `mkdir -p experiments/{deepagents-repl,eks-agent,agentcore-ada,vfs-workspace}`.
2. `git mv runtime/ experiments/deepagents-repl/runtime/`.
3. `git mv agent.py experiments/deepagents-repl/agent.py`.
4. `git mv workspace/ experiments/deepagents-repl/workspace/`.
5. `git mv eks/ experiments/eks-agent/`.
6. `git mv ada/ experiments/agentcore-ada/`.
7. For each experiment, audit imports and create its own `pyproject.toml` with the subset of root's dep list it actually uses. Root's current dep set spans multiple experiments — do not blindly move root's `pyproject.toml` into any single experiment.
   - `deepagents-repl`: `boto3`, `deepagents`, `mirage-ai[s3]`, `pydantic-monty`, `langchain`, `langchain-anthropic`, `python-dotenv`, `claude-agent-sdk`.
   - `vff`: `fastmcp`, `mirage-ai[s3]`, `pydantic-monty`, `claude-agent-sdk`, `python-dotenv`.
   - `eks-agent`: audit `experiments/eks-agent/app/*.py` imports.
   - `agentcore-ada`: audit `experiments/agentcore-ada/agentcore/`; may be pure infra (no `pyproject.toml`).
   - (These sets are best-guesses from a first pass; final sets come from audit.)
8. In each experiment folder, run `uv init` (or manually write `pyproject.toml` + `.python-version`), then `uv sync` to produce its own `uv.lock` and `.venv`.
9. Delete root `pyproject.toml`, `uv.lock`, `.python-version`, `.venv/`, and any root `__pycache__/`.
10. Update root `.gitignore` to ignore per-experiment `.venv/` and `__pycache__/`.
11. Create root `README.md` as an experiment index (one line per experiment).
12. Verify every experiment installs (`uv sync` in each folder) and imports resolve. Any `experiments/*` script that ran under the root venv must now run under its own venv.
13. Scaffold `experiments/vfs-workspace/` fresh — `uv init service/`, `pnpm create svelte@latest ui`, plus `runtime-image/`.

**Blast-radius flag:** steps 8–9 (extracting per-experiment dep sets) are the highest-risk step. Experiments do not import each other today, so blast radius is contained; each `pyproject.toml` derived by auditing imports (grep or `pipreqs`), then `uv sync` verifies.

## 4. `vfs-workspace/` internal layout

```
experiments/vfs-workspace/
├── README.md
├── docker-compose.yml                 # dev orchestration: service + ui
├── service/                           # Python project
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .python-version
│   ├── src/
│   │   ├── mirage_runtimes/
│   │   │   ├── __init__.py            # registers runtime classes
│   │   │   ├── docker_local/
│   │   │   │   ├── engine.py
│   │   │   │   ├── python.py          # MountLocalPython(PythonRuntime)
│   │   │   │   └── js.py              # MountLocalJs(JsRuntime)
│   │   │   └── code_interpreter/
│   │   │       ├── engine.py
│   │   │       └── python.py          # CodeInterpreterPython(PythonRuntime)
│   │   └── workspace_service/
│   │       ├── main.py                # FastAPI app entrypoint
│   │       ├── config.py              # YAML loader, user → workspace map
│   │       ├── workspaces.py          # WorkspaceManager (per-user Mirage ws cache)
│   │       ├── auth.py                # X-User-Id middleware (Phase 0)
│   │       ├── rest/
│   │       │   ├── files.py           # tree, read, write, delete
│   │       │   └── exec.py            # POST /exec → ws.execute()
│   │       └── mcp/
│   │           └── server.py          # FastMCP HTTP, per-workspace mount
│   ├── workspaces.yaml                # example config
│   └── Dockerfile                     # service image (optional for MVP)
├── runtime-image/                     # base image spawned by docker-local runtime
│   ├── Dockerfile                     # ubuntu + mountpoint-s3 + python + node
│   └── entrypoint.sh                  # mounts S3 via env, then sleeps
└── ui/                                # Node project (SvelteKit)
    ├── package.json
    ├── pnpm-lock.yaml
    ├── svelte.config.js
    ├── tailwind.config.ts
    └── src/
        ├── app.html
        ├── lib/
        │   ├── api.ts                 # REST client
        │   └── components/            # shadcn-svelte components
        └── routes/
            ├── +page.svelte           # workspace list
            └── w/[id]/+page.svelte    # tree + preview + exec panes
```

## 5. Layered architecture

```
┌────────────────────────────────────────────────────────────┐
│  Svelte UI (SvelteKit + shadcn + Tailwind)                │
│  - list workspaces  - file tree  - preview  - exec pane   │
└────────────────────────┬───────────────────────────────────┘
                         │ HTTP REST (X-User-Id header)
                         ▼
┌────────────────────────────────────────────────────────────┐
│  Workspace Service (FastAPI)                              │
│  - REST: /workspaces, /files, /tree, /exec                │
│  - MCP:  /mcp/workspaces/{id} (FastMCP HTTP)              │
│  - Config: user → { s3, runtime }                          │
│  - WorkspaceManager: per-user Mirage Workspace cache       │
│  - Idle sweeper (default 15 min)                           │
└────────────────────────┬───────────────────────────────────┘
                         │ owns Mirage Workspace instances
                         ▼
┌────────────────────────────────────────────────────────────┐
│  Mirage Workspace (per user)                              │
│  - mounts: { "disk": S3Resource(user's prefix) }          │
│  - runtimes: [ chosen adapter instance ]                   │
│  - ws.io.{read,write,edit,grep,glob,ls,delete}            │
│  - ws.execute("python3 -c ...")                            │
└────────────────────────┬───────────────────────────────────┘
                         │ dispatches python3/python/node → runtime
                         ▼
┌────────────────────────────────────────────────────────────┐
│  Runtime Adapter (one of, chosen per user config)         │
│  ┌────────────────────────────────────────────────────┐   │
│  │ docker-local                                       │   │
│  │  - container per workspace                          │   │
│  │  - mountpoint-s3 at /workspace inside container    │   │
│  │  - `docker exec ... python -c ...`                  │   │
│  └────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────┐   │
│  │ code-interpreter                                   │   │
│  │  - AgentCore CodeInterpreter session               │   │
│  │  - S3 filesystem config on session create          │   │
│  │  - execute_code API call, persistent kernel        │   │
│  └────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘
```

The MCP surface is exposed now for parity with the eventual agent service, even though no agent consumes it in Phase 0. This avoids a wire-protocol rewrite later.

## 6. Config model

`experiments/vfs-workspace/service/workspaces.yaml`:

```yaml
users:
  chris:
    s3_bucket: mirage-test-chris
    s3_region: ap-southeast-1
    s3_prefix: workspaces/chris
    runtime: docker-local              # or: code-interpreter
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
    aws_env_forwarding: true           # forward host AWS_* env to container
  code-interpreter:
    agentcore_region: us-east-1
    session_timeout_seconds: 900
```

- Loaded at service start. No hot reload for Phase 0.
- No secrets in this file; AWS credentials come from ambient env (host `AWS_*` for local, IAM role in cloud).
- One workspace per user in Phase 0. `POST /workspaces/{id}/open` where `{id}` is `user_id`.

## 7. Workspace lifecycle (`workspace_service/workspaces.py`)

```python
class WorkspaceManager:
    def open(self, user_id: str) -> Workspace: ...
    def close(self, user_id: str) -> None: ...
    def get_or_open(self, user_id: str) -> Workspace: ...
    def close_idle(self) -> None: ...  # background task, N-minute idle
```

- Cache is process-local dict `{user_id: Workspace}`.
- `open` = look up config → build `S3Resource` → construct runtime instance → construct `Workspace({mount: resource}, runtimes=[runtime])` → cache.
- Runtime `__init__` performs mount / CodeInterpreter session create. Runtime destructor / explicit `close` performs unmount / session delete.
- Idle sweeper runs every 60s, closes workspaces untouched for 15 minutes.
- Every request updates the workspace's `last_touched` timestamp.
- Race between sweeper and active request is theoretical (only closes idle workspaces); punt for MVP.

## 8. Runtime adapters

### 8.1 `docker-local`

**Files:** `mirage_runtimes/docker_local/{engine.py, python.py, js.py}`.

**Base image (`runtime-image/Dockerfile`):**

```dockerfile
FROM public.ecr.aws/lts/ubuntu:24.04
RUN apt-get update && apt-get install -y \
    curl fuse python3 python3-pip nodejs npm ca-certificates \
 && ARCH=$(uname -m) \
 && curl -o /tmp/ms.deb "https://s3.amazonaws.com/mountpoint-s3-release/latest/${ARCH}/mount-s3.deb" \
 && dpkg -i /tmp/ms.deb && rm /tmp/ms.deb
WORKDIR /workspace
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
```

**`entrypoint.sh`:** mounts S3 using env vars (`S3_BUCKET`, `S3_PREFIX`, `AWS_*`) at `/workspace` via `mount-s3 --foreground --metadata-ttl 0 --allow-delete --allow-overwrite`, then `exec "$@"`.

**Engine (shared across Python/JS subclasses):**

```python
class DockerLocalEngine:
    def __init__(self, s3_bucket: str, s3_prefix: str, image: str,
                 aws_env: dict[str, str] | None = None):
        self._container_name = f"mirage-ws-{uuid4().hex[:8]}"
        self._image = image
        self._env = {"S3_BUCKET": s3_bucket, "S3_PREFIX": s3_prefix,
                     **(aws_env or _aws_env_from_host())}

    def start(self) -> None: ...        # docker run -d ... --cap-add SYS_ADMIN --device /dev/fuse
    async def run(self, interpreter: str, args: RunArgs) -> RunResult: ...
    def stop(self) -> None: ...         # docker stop
```

**Python subclass:**

```python
class MountLocalPython(PythonRuntime):
    name = "docker-local"
    reach: RuntimeReach = "process"
    config_cls = DockerLocalConfig
    def __init__(self, captures=None, config=None, script=None):
        super().__init__(captures, config, script)
        self._engine = DockerLocalEngine(...); self._engine.start()
    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run("python3", args)
    def __del__(self):
        try: self._engine.stop()
        except Exception: pass
```

**JS subclass:** identical shape, subclass of `JsRuntime`, calls `self._engine.run("node", args)`.

**Design points:**

- One container per workspace, long-lived until workspace closes.
- `SYS_ADMIN + /dev/fuse` required for in-container mountpoint-s3.
- Container `CWD` is `/workspace`, which is the mount → scripts read/write via plain relative paths.
- `--metadata-ttl 0` disables metadata cache to keep the mount consistent with external S3 writes; can dial up later.
- Same image serves Python + Node; language chosen by subclass's interpreter binary.
- Orphan cleanup at service startup: `docker ps -f name=mirage-ws-* -q | xargs docker stop` to reap containers left by a crashed service.

**Risks:**

- Docker Desktop must be running. Health check at service start.
- Privileged flags (`SYS_ADMIN`, `/dev/fuse`) fine for local dev, needs re-assessment before production.
- mountpoint-s3 limitation: random writes (`f.seek(0); f.write(...)` mid-file) fail. Append-only and full-object writes work. Documented as a known limitation. Switch to S3 Files later if it bites.
- macOS host: docker containers still Linux-inside, so FUSE runs in container. Host stays FUSE-free.

### 8.2 `code-interpreter`

**Files:** `mirage_runtimes/code_interpreter/{engine.py, python.py}`. Python only; no JS subclass (AWS Python-only).

**Engine:**

```python
class CodeInterpreterEngine:
    def __init__(self, region: str, s3_bucket: str, s3_prefix: str,
                 session_timeout: int = 900):
        self._client = boto3.client("bedrock-agentcore", region_name=region)
        self._session_id: str | None = None
        ...

    def open(self) -> None:
        resp = self._client.create_code_interpreter_session(
            fileSystemConfig={"s3": {"bucketName": ..., "prefix": ...,
                                      "sessionTimeoutSeconds": ...}},
        )
        self._session_id = resp["sessionId"]

    async def run(self, args: RunArgs) -> RunResult:
        resp = await asyncio.to_thread(
            self._client.execute_code,
            sessionId=self._session_id, code=args.code, language="python",
        )
        return RunResult(stdout=..., stderr=..., exit_code=...)

    def close(self) -> None: ...
```

**Python subclass:**

```python
class CodeInterpreterPython(PythonRuntime):
    name = "code-interpreter"
    reach: RuntimeReach = "remote"
    config_cls = CodeInterpreterConfig
    def __init__(self, captures=None, config=None, script=None):
        super().__init__(captures, config, script)
        self._engine = CodeInterpreterEngine(...); self._engine.open()
    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run(args)
    def __del__(self):
        try: self._engine.close()
        except Exception: pass
```

**Design points:**

- Boto3 API shapes (`create_code_interpreter_session`, `execute_code`) are placeholders. Real signatures verified during implementation and adjusted in `engine.py`; subclass unchanged.
- Persistent kernel — imports and variable state survive across `run()` calls within the same session. Matches notebook semantics.
- S3 filesystem is native to the CodeInterpreter session; no drift with other writers because the CodeInterpreter environment reads/writes through AWS-managed mount.

**Risks:**

- Requires AWS credentials with `bedrock-agentcore` permissions and CodeInterpreter feature enabled in target account.
- Cross-region latency: local service in one region, CodeInterpreter in another → per-run round trip. Configure `agentcore_region` per environment.
- Session timeout (default 15 min) — extend or refresh proactively before timeout. MVP: let it expire, next request reopens.

## 9. HTTP surfaces

### 9.1 REST (`workspace_service/rest/`)

Base URL: `http://<host>:<port>`. All requests carry `X-User-Id: <user>` for Phase 0 auth.

```
GET    /health                                     liveness
GET    /workspaces                                 list workspaces for auth'd user (Phase 0: one)
POST   /workspaces/{id}/open                       ensure open, returns { status, runtime }
POST   /workspaces/{id}/close                      teardown
GET    /workspaces/{id}/tree?path=/&depth=N        recursive tree; capped depth for large trees
GET    /workspaces/{id}/files/{path...}            read; content-type sniffed
PUT    /workspaces/{id}/files/{path...}            write (body = bytes)
DELETE /workspaces/{id}/files/{path...}            delete
POST   /workspaces/{id}/exec                       body: { language: "python"|"node",
                                                            code: str, args?: [str],
                                                            stdin?: str, env?: {} }
                                                    returns { stdout, stderr, exit_code, elapsed_ms }
```

- `tree` performs a server-side walk via `ws.io.readdir`, capped depth, no pagination for Phase 0.
- `exec` returns buffered response. Streaming is a follow-up.
- Language dispatch: `exec` body's `language` field maps to command capture (`python3` or `node`), passed to `ws.execute`.

### 9.2 MCP (`workspace_service/mcp/server.py`)

- FastMCP HTTP server, one server instance per open workspace, mounted at `/mcp/workspaces/{id}`.
- Tool set mirrors mirage's built-in tools (`mirage.agents.claude_agent_sdk.server._MirageTools`): `read`, `write`, `edit`, `grep`, `glob`, `ls`, `delete`, `execute`.
- Auth: same `X-User-Id` header validated at connect.
- Purpose: parity with the future agent service. No agent consumes this in Phase 0. Sanity test with a manual MCP client.

## 10. UI (`ui/`)

**Stack:** SvelteKit (Svelte 5), shadcn-svelte, Tailwind 4, TypeScript, pnpm.

**No auth.** All requests set `X-User-Id: chris` (or from a `PUBLIC_USER_ID` env var) in the fetch layer.

**Screens:**

1. **`/` — workspace list.**
   - `GET /workspaces` → render one-line-per-workspace list.
   - Click → navigate to `/w/{id}`.

2. **`/w/{id}` — three-pane workspace view.**
   - Header: workspace id, runtime badge (from `/workspaces/{id}/open` response).
   - Left pane: file tree from `GET /tree`. Collapsible. Click file → load in middle pane.
   - Middle pane: file preview via `GET /files/{path}`. Monospace. Read-only for Phase 0.
   - Right pane: exec.
     - Language dropdown: `Python` | `Node`. `Node` disabled when runtime is `code-interpreter`.
     - Code textarea (monospace, tab-indent).
     - "Run" button → `POST /exec`.
     - Output pane: stdout, stderr, exit code, elapsed ms.

No state persistence. Refresh re-fetches. No SSR (SPA mode acceptable — SvelteKit's `adapter-static`).

## 11. Failure modes and error surfacing

- Config lookup miss → 404.
- Mount / session create failure → 500 with structured error body: `{ error: "mount_failed", detail: "..." }`. Logged with full traceback server-side.
- `docker` not on PATH / daemon not running → surfaced at service startup health check; `docker-local` runtimes marked unavailable in config summary.
- AWS creds missing / CodeInterpreter unauthorized → 502 on `open`, logged.
- Exec failure (non-zero exit) → 200 response with `exit_code != 0`; UI shows stderr and exit code. Not an HTTP error.
- Exec timeout → 200 response with `exit_code: -1`, `stderr: "timeout after Ns"`, actual process killed by runtime engine.
- MCP tool failure → returned as MCP `is_error: true` result per spec.

## 12. Development workflow

- `experiments/vfs-workspace/docker-compose.yml` brings up:
  - `service/` (mounted volume for dev), listening on port 8000
  - `ui/` (Vite dev server), listening on 5173
- `runtime-image/` built manually once: `cd runtime-image && docker build -t mirage-runtime:latest .`
- Manual smoke test: `curl -H "X-User-Id: chris" http://localhost:8000/workspaces/chris/tree`, then `POST /exec` with a small `print("hi")` script.
- End-to-end sanity: browse UI, click file, run code, verify output matches.

## 13. Known open items

Fold into implementation once discovered:

- **AgentCore CodeInterpreter API shapes** — placeholder boto3 calls in Section 8.2 must be verified against real API. Version mismatch could force wrapping via a different service (SDK, HTTP, or the `bedrock-runtime-agentcore` client, etc.).
- **mountpoint-s3 macOS x86 vs ARM inside container** — Docker Desktop on Apple Silicon uses ARM Linux; the base image must pull the arm64 .deb. Handled by `ARCH=$(uname -m)` in Dockerfile; verify build succeeds on both.
- **Existing experiment dep sets** — steps 8–9 of the reshuffle require per-experiment `pyproject.toml` extraction. Audit imports before finalizing each.

## 14. Success criteria

Phase 0 is done when:

1. Repo is fully reshuffled; each experiment installs cleanly in isolation (`uv sync` in each folder passes).
2. `experiments/vfs-workspace/service/` starts, loads `workspaces.yaml`, responds to `GET /health`.
3. For a configured user with `runtime: docker-local`: `POST /workspaces/{id}/open` starts a container, `GET /tree` returns the S3 prefix's contents, `POST /exec` with `print("hi")` returns `stdout: "hi\n"`.
4. For a configured user with `runtime: code-interpreter`: same three operations succeed against a real AgentCore session.
5. UI renders workspace list, tree, file preview, and exec pane. Running code from the UI produces output.
6. HTTP MCP endpoint at `/mcp/workspaces/{id}` responds to `tools/list` and can execute the `read` and `execute` tools when hit with a raw MCP client.
7. Idle sweeper closes an untouched workspace after configured timeout.

## 15. Follow-up specs (not this document)

- Agent service consuming workspace MCP + Claude SDK + chat UI.
- Keycloak / OIDC integration replacing `X-User-Id`.
- `sync-local` runtime adapter for non-mountable sources (GitHub, SharePoint).
- Multi-workspace-per-user.
- Production deployment (ECS/Fargate with `docker-aws` runtime using S3 Files NFS).
- Observability (traces, metrics, structured logs).
- WebSocket streaming for exec output.
