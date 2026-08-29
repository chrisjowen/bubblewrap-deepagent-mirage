from dataclasses import dataclass

from mirage.runtime.config import RuntimeConfig


@dataclass(frozen=True, slots=True)
class CodeInterpreterConfig(RuntimeConfig):
    region: str = "us-east-1"
    code_interpreter_identifier: str = "aws.codeinterpreter.v1"
    session_timeout_seconds: int = 900
    session_name: str | None = None
