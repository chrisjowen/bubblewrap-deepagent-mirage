"""CodeInterpreter package — one interface, docker + aws implementations."""

from code_interpreter.aws import AwsCodeInterpreter, AwsConfig
from code_interpreter.docker import DockerCodeInterpreter, DockerConfig
from code_interpreter.protocol import (
    CodeInterpreterSession,
    ExecResult,
    Language,
    SessionInfo,
    Task,
    TaskStatus,
)
from workspace_service.config import UserSpec


def build(user: UserSpec, runtime_spec: dict) -> CodeInterpreterSession:
    """Factory: pick docker or aws implementation based on the user's config."""
    name = user.runtime
    if name == "docker-local":
        cfg = DockerConfig(
            s3_bucket=user.s3_bucket,
            s3_prefix=user.s3_prefix,
            image=runtime_spec.get("image", "mirage-runtime:latest"),
            aws_env_forwarding=runtime_spec.get("aws_env_forwarding", True),
        )
        return DockerCodeInterpreter(config=cfg)
    if name == "code-interpreter":
        cfg = AwsConfig(
            region=runtime_spec.get("region", user.s3_region),
            code_interpreter_identifier=runtime_spec["code_interpreter_identifier"],
            session_timeout_seconds=runtime_spec.get("session_timeout_seconds", 900),
        )
        return AwsCodeInterpreter(config=cfg)
    raise ValueError(f"unknown runtime: {name}")


__all__ = [
    "AwsCodeInterpreter",
    "AwsConfig",
    "CodeInterpreterSession",
    "DockerCodeInterpreter",
    "DockerConfig",
    "ExecResult",
    "Language",
    "SessionInfo",
    "Task",
    "TaskStatus",
    "build",
]
