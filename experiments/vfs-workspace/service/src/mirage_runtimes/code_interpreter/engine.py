from __future__ import annotations

import asyncio
from uuid import uuid4

import boto3

from mirage.runtime.types import RunArgs, RunResult

from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig


class CodeInterpreterEngine:
    """AgentCore CodeInterpreter session wrapper.

    Sandboxed remote runtime. Filesystem is isolated from the workspace's
    S3 mount by default — use `writeFiles` / `readFiles` invocations for
    I/O, or have the executed code call boto3 directly if it needs S3.
    """

    _SERVICE_NAME = "bedrock-agentcore"

    def __init__(self, config: CodeInterpreterConfig) -> None:
        self._config = config
        self._client = boto3.client(self._SERVICE_NAME, region_name=config.region)
        self._session_id: str | None = None

    def open(self) -> None:
        resp = self._client.start_code_interpreter_session(
            codeInterpreterIdentifier=self._config.code_interpreter_identifier,
            name=self._config.session_name or f"vfs-ws-{uuid4().hex[:8]}",
            sessionTimeoutSeconds=self._config.session_timeout_seconds,
        )
        self._session_id = resp["sessionId"]

    async def run(self, args: RunArgs) -> RunResult:
        if not self._session_id:
            raise RuntimeError("engine not open")

        def _invoke() -> RunResult:
            resp = self._client.invoke_code_interpreter(
                codeInterpreterIdentifier=self._config.code_interpreter_identifier,
                sessionId=self._session_id,
                name="executeCode",
                arguments={"code": args.code, "language": "python"},
            )
            return _parse_stream(resp["stream"])

        return await asyncio.to_thread(_invoke)

    def close(self) -> None:
        if not self._session_id:
            return
        try:
            self._client.stop_code_interpreter_session(
                codeInterpreterIdentifier=self._config.code_interpreter_identifier,
                sessionId=self._session_id,
            )
        finally:
            self._session_id = None


def _parse_stream(stream) -> RunResult:
    stdout = b""
    stderr: bytes | None = None
    exit_code = 0
    for event in stream:
        if "result" in event:
            r = event["result"] or {}
            struct = r.get("structuredContent") or {}
            if "stdout" in struct:
                stdout = struct["stdout"].encode("utf-8")
            if "stderr" in struct and struct["stderr"]:
                stderr = struct["stderr"].encode("utf-8")
            if "exitCode" in struct:
                exit_code = int(struct["exitCode"])
            if r.get("isError") and exit_code == 0:
                exit_code = 1
            break
        for exc_key in (
            "accessDeniedException", "conflictException", "internalServerException",
            "resourceNotFoundException", "serviceQuotaExceededException",
            "throttlingException", "validationException",
        ):
            if exc_key in event:
                msg = (event[exc_key] or {}).get("message", exc_key)
                return RunResult(stdout=b"", stderr=msg.encode("utf-8"), exit_code=1)
    return RunResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
