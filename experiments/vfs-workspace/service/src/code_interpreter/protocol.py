"""Common shape for a code interpreter session.

Session-scoped execution surface, mirroring AWS Bedrock AgentCore
CodeInterpreter's invoke_code_interpreter tool set: executeCode,
executeCommand, startCommandExecution, getTask, stopTask.

File operations are NOT part of this abstraction — they live on the
Mirage workspace layer (session-less, always available), which is
distinct from the interpreter runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Language = Literal["python", "node", "bash"]
TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int = 0


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    status: TaskStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    execution_time_ms: int = 0


@dataclass
class SessionInfo:
    session_id: str
    runtime: str  # "docker-local" | "code-interpreter"
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class CodeInterpreterSession(Protocol):
    """One session — one container / one AgentCore session."""

    @property
    def session_id(self) -> str: ...

    @property
    def runtime(self) -> str: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    # code / shell
    async def execute_code(
        self,
        code: str,
        language: Language = "python",
        clear_context: bool = False,
    ) -> ExecResult: ...

    async def execute_command(self, command: str) -> ExecResult: ...

    # async long-running command
    async def start_command_execution(self, command: str) -> str: ...
    async def get_task(self, task_id: str) -> Task: ...
    async def stop_task(self, task_id: str) -> None: ...
