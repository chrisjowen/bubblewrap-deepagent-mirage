"""Build the deepagents agent for EKS Fargate.

Env-driven only — no AgentCore Identity fallback. Set:
- `ANTHROPIC_API_KEY`
- `S3_BUCKET`, `S3_REGION`, `S3_KEY_PREFIX`
- `SANDBOX_DIR` (default `/tmp/sandbox`)
"""

from __future__ import annotations

import os

from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from mirage.resource.s3 import S3Config, S3Resource

from runtime import MirageSandboxBackend

SYSTEM_PROMPT = """You are a helpful assistant with file and shell tools.

WORKSPACE-ONLY FILE ACCESS — HARD RULE:
The workspace is your ONLY filesystem. The host filesystem is off-limits.

Path model:
- **File tools** (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`) use
  virtual workspace paths rooted at `/`.
- **`execute`** runs a shell command in the workspace directory. Use ONLY relative
  paths in shell: `python3 script.py`, `cat report.md`, `ls ./sub/`.

FORBIDDEN in shell commands:
- Absolute paths: `/tmp/...`, `/etc/...`, `/var/...`, `/home/...`, `/Users/...`,
  `/root/...`, `/opt/...`, `/usr/...`.
- Home shortcuts: `~`, `$HOME`.
- Privilege escalation: `sudo`.

Skills:
Available skills live under `/skills/`. Each skill is a directory with a `SKILL.md`.

Be concise."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def build_agent():
    _require("ANTHROPIC_API_KEY")
    bucket = _require("S3_BUCKET")
    region = _require("S3_REGION")
    key_prefix = _require("S3_KEY_PREFIX")
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
