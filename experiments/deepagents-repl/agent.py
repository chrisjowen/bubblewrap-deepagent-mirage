"""Minimal deepagents REPL backed by Claude Sonnet 4.5."""

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

from deepagents import create_deep_agent
from mirage.resource.s3 import S3Config, S3Resource

from runtime import BwrapBackend, MirageSandboxBackend

S3_BUCKET = "mirage-test-chris"
S3_REGION = "ap-southeast-1"
SANDBOX_SCRATCH = Path("workspace/sandbox")

SYSTEM_PROMPT = (
    "You are a helpful assistant with file and shell tools. "
    "The workspace is your single filesystem — read/write/edit files freely "
    "and use `execute` for shell commands. Be concise."
)


def reset_sandbox(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def build_agent(key_prefix: str):
    model = init_chat_model(
        model="anthropic:claude-sonnet-4-5-20250929",
        temperature=0.0,
    )
    sandbox_dir = str(SANDBOX_SCRATCH)
    backend = MirageSandboxBackend(
        resource=S3Resource(
            S3Config(bucket=S3_BUCKET, region=S3_REGION, key_prefix=key_prefix)
        ),
        sandbox=BwrapBackend(root_dir=sandbox_dir),
        sandbox_dir=sandbox_dir,
    )
    return create_deep_agent(
        model=model,
        backend=backend,
        system_prompt=SYSTEM_PROMPT,
    )


def extract_reply(result) -> str:
    messages = result.get("messages", [])
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content:
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = "".join(parts).strip()
                if text:
                    return text
            elif isinstance(content, str) and content.strip():
                return content.strip()
    return "(no reply)"


def _truncate(s: str, n: int = 200) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def print_new_messages(messages, seen: int) -> None:
    for msg in messages[seen:]:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
            print(f"  → {name}({_truncate(repr(args), 240)})", file=sys.stderr)
        if type(msg).__name__ == "ToolMessage":
            name = getattr(msg, "name", "?")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            print(f"  ← {name}: {_truncate(content, 240)}", file=sys.stderr)


def main() -> int:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1
    if len(sys.argv) != 2:
        print(f"usage: python {sys.argv[0]} <s3-folder>", file=sys.stderr)
        print(f"       bucket=s3://{S3_BUCKET}/<s3-folder>/  region={S3_REGION}", file=sys.stderr)
        return 2

    key_prefix = sys.argv[1].strip("/")
    reset_sandbox(SANDBOX_SCRATCH)
    print(f"[boot] sandbox reset: {SANDBOX_SCRATCH}", file=sys.stderr)
    print(f"[boot] mirage backing: s3://{S3_BUCKET}/{key_prefix}/", file=sys.stderr)

    agent = build_agent(key_prefix)
    history = []
    print("deepagent REPL. Type 'quit' or Ctrl-C to exit.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            return 0

        history.append({"role": "user", "content": user_input})
        seen = len(history)
        result = agent.invoke({"messages": history})
        history = result.get("messages", history)
        print_new_messages(history, seen)
        print(f"agent> {extract_reply(result)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
