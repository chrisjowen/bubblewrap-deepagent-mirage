"""CodeInterpreter port + adapters.

Import order matters: adapter modules self-register on import, so we
import them here so the registry is populated by the time callers do
`from code_interpreter import build`.
"""

from code_interpreter.protocol import (
    CodeInterpreterSession,
    ExecResult,
    Language,
    SessionInfo,
    Task,
    TaskStatus,
)
from code_interpreter.registry import StorageBinding, build, known, register

# Side-effect imports: adapters register into the registry at import.
from code_interpreter import aws as _aws  # noqa: F401
from code_interpreter import docker as _docker  # noqa: F401
from code_interpreter.aws import AwsCodeInterpreter, AwsConfig
from code_interpreter.docker import DockerCodeInterpreter, DockerConfig


__all__ = [
    "AwsCodeInterpreter",
    "AwsConfig",
    "CodeInterpreterSession",
    "DockerCodeInterpreter",
    "DockerConfig",
    "ExecResult",
    "Language",
    "SessionInfo",
    "StorageBinding",
    "Task",
    "TaskStatus",
    "build",
    "known",
    "register",
]
