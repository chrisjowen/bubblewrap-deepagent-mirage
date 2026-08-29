"""Build the deepagents agent for AgentCore runtime.

Uses `MirageSandboxBackend` with a `LocalShellBackend` sandbox — AgentCore
already isolates the runtime, so no bwrap layer is needed.

Env vars (set via agentcore.json envVars + credential provider):
- `ANTHROPIC_API_KEY` — Claude key (populated by AgentCore credential wire-up)
- `S3_BUCKET` — mirage source bucket
- `S3_REGION` — bucket region
- `S3_KEY_PREFIX` — folder within the bucket
- `SANDBOX_DIR` — local scratch dir (default `/tmp/sandbox`)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from mirage.resource.s3 import S3Config, S3Resource

from runtime import MirageSandboxBackend

SYSTEM_PROMPT = """You are a helpful assistant with file and shell tools.

WORKSPACE-ONLY FILE ACCESS — HARD RULE:
The workspace is your ONLY filesystem. The host filesystem is off-limits. Any read
or write outside the workspace is a bug — files will be lost and secrets leaked.

Path model:
- **File tools** (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`) use
  virtual workspace paths rooted at `/`. e.g. `read_file("/report.md")`.
- **`execute`** runs a shell command in the workspace directory. Use ONLY relative
  paths in shell: `python3 script.py`, `cat report.md`, `ls ./sub/`. The file
  `report.md` you see via `read_file("/report.md")` is the same as `report.md` in
  the shell.

FORBIDDEN in shell commands (`execute`):
- Absolute paths: `/tmp/...`, `/etc/...`, `/var/...`, `/home/...`, `/Users/...`,
  `/root/...`, `/opt/...`, `/usr/...` — any path starting with `/`.
- Home shortcuts: `~`, `$HOME`.
- Navigation off workspace: `cd /`, `cd ~`, `cd ..` past root.
- Downloading/writing to non-workspace paths: `curl -o /tmp/...`, `wget -O ~/...`.
- Privilege escalation: `sudo`.

FORBIDDEN in file tools:
- Writing to virtual paths that suggest host locations (`/tmp/foo`, `/etc/foo`).
  Everything writes to durable workspace storage — pick real, meaningful paths.

If you need scratch space, put it under `/tmp-workspace/` inside the workspace, not
`/tmp`. If you need to read config, it must already be in the workspace.

Skills:
Available skills live under `/skills/`. Each skill is a directory with a `SKILL.md`.
Read the SKILL.md (with `read_file(..., limit=1000)`) when its description matches
the task, then follow it.

Be concise."""


def _hydrate_env_from_agentcore_json() -> None:
    """Dev fallback: local `agentcore dev` doesn't auto-inject `envVars` from
    `agentcore.json`. Walk up from this file to find it and hydrate `os.environ`.
    Existing env vars win — never overwrite what the caller set.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "agentcore" / "agentcore.json"
        if not candidate.is_file():
            continue
        try:
            spec = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for runtime in spec.get("runtimes", []):
            for env in runtime.get("envVars", []):
                os.environ.setdefault(env["name"], env["value"])
        return


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _resolve_anthropic_key() -> str:
    """Resolve Anthropic key from env (local dev) or AgentCore Identity (runtime)."""
    for candidate in ("ANTHROPIC_API_KEY", "AGENTCORE_CREDENTIAL_ANTHROPIC", "AGENTCORE_CREDENTIAL_ADAANTHROPIC"):
        value = os.environ.get(candidate)
        if value:
            os.environ["ANTHROPIC_API_KEY"] = value
            return value

    value = _fetch_key_from_agentcore_identity(provider_name="anthropic")
    os.environ["ANTHROPIC_API_KEY"] = value
    return value


def _fetch_key_from_agentcore_identity(provider_name: str) -> str:
    """Fetch API key from AgentCore Identity via workload access token.

    Raises with concrete cause so runtime logs make the failure visible.
    """
    import asyncio

    try:
        from bedrock_agentcore.runtime.context import BedrockAgentCoreContext
        from bedrock_agentcore.services.identity import IdentityClient
    except ImportError as exc:
        raise RuntimeError(f"bedrock_agentcore SDK not importable: {exc}") from exc

    wat = BedrockAgentCoreContext.get_workload_access_token()
    if not wat:
        raise RuntimeError("no workload access token in context (WAT is per-request; agent must be built inside a handler)")

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    async def _go() -> str:
        return await IdentityClient(region).get_api_key(
            provider_name=provider_name,
            agent_identity_token=wat,
        )

    try:
        return asyncio.run(_go())
    except RuntimeError:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(_go())).result()


def build_agent():
    _hydrate_env_from_agentcore_json()
    _resolve_anthropic_key()
    bucket = _require_env("S3_BUCKET")
    region = _require_env("S3_REGION")
    key_prefix = _require_env("S3_KEY_PREFIX")
    sandbox_dir = os.environ.get("SANDBOX_DIR", "/tmp/sandbox")

    model = init_chat_model(
        model="anthropic:claude-sonnet-4-5-20250929",
        temperature=0.0,
    )
    backend = MirageSandboxBackend(
        resource=S3Resource(S3Config(bucket=bucket, region=region, key_prefix=key_prefix)),
        sandbox=LocalShellBackend(root_dir=sandbox_dir),
        sandbox_dir=sandbox_dir,
    )
    return create_deep_agent(
        model=model,
        backend=backend,
        system_prompt=SYSTEM_PROMPT,
        skills=["/skills/"],
        checkpointer=InMemorySaver(),
    )
