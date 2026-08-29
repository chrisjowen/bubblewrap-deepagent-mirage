"""Claude-SDK agent locked to the vff HTTP MCP server.

Run the server first (in another shell):

    VFF_S3_PREFIX=<prefix> uv run python -m experiments.vff.server

Then:

    VFF_S3_PREFIX=<prefix> uv run python -m experiments.vff.agent
"""

from __future__ import annotations

import asyncio
import os
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from dotenv import load_dotenv

VFF_HOST = os.getenv("VFF_HOST", "127.0.0.1")
VFF_PORT = int(os.getenv("VFF_PORT", "8765"))
VFF_URL = os.getenv("VFF_URL", f"http://{VFF_HOST}:{VFF_PORT}/mcp")

BLOCKED = ["Write", "Edit", "MultiEdit", "Bash", "NotebookEdit"]

VFF_TOOLS = [
    "mcp__vff__read",
    "mcp__vff__write",
    "mcp__vff__edit",
    "mcp__vff__grep",
    "mcp__vff__glob",
    "mcp__vff__ls",
    "mcp__vff__delete",
    "mcp__vff__execute_code",
]

SYSTEM_PROMPT = (
    "You are a research assistant with a virtual filesystem exposed via the "
    "`vff` MCP server (mirage-backed S3). All file I/O — read, write, edit, "
    "grep, glob, ls, delete — MUST go through the vff tools. Local Write, "
    "Edit, and Bash tools are disabled. Use `mcp__vff__execute_code` to run "
    "Python in a sandboxed monty interpreter. Be concise."
)


def _describe_tool_input(block: ToolUseBlock) -> str:
    args = block.input or {}
    preview = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
    return f"{block.name}({preview})"


def _short(value: object, limit: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def run_once(prompt: str) -> None:
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-5",
        system_prompt=SYSTEM_PROMPT,
        disallowed_tools=BLOCKED,
        allowed_tools=VFF_TOOLS,
        mcp_servers={
            "vff": {"type": "http", "url": VFF_URL},
        },
        permission_mode="bypassPermissions",
        max_turns=20,
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(f"agent> {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        print(f"  → {_describe_tool_input(block)}")
            elif isinstance(msg, UserMessage):
                for block in msg.content if isinstance(msg.content, list) else []:
                    if isinstance(block, ToolResultBlock):
                        text = block.content if isinstance(block.content, str) else str(block.content)
                        print(f"  ← {_short(text, 240)}")
            elif isinstance(msg, ResultMessage):
                print(f"[done] turns={msg.num_turns} cost=${msg.total_cost_usd or 0:.4f}")


def main() -> int:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1
    prompt = " ".join(sys.argv[1:]).strip() or (
        "Using the vff MCP tools: write a file called 'hello.txt' with the "
        "content 'hello from vff', then read it back to confirm, then use "
        "execute_code to compute and print 6*7."
    )
    print(f"[vff-agent] MCP: {VFF_URL}")
    print(f"[vff-agent] prompt: {prompt}\n")
    asyncio.run(run_once(prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
