"""AWS Bedrock AgentCore CodeInterpreter implementation.

Wraps start_code_interpreter_session / invoke_code_interpreter /
stop_code_interpreter_session. Optionally attaches S3 Files (or EFS)
access-point mounts to the session via `filesystemConfigurations`, so
the sandbox sees the workspace bucket at a real mount path like
/mnt/s3data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import boto3

from code_interpreter.protocol import (
    CodeInterpreterSession,
    ExecResult,
    Language,
    Task,
)


@dataclass
class AwsConfig:
    region: str
    code_interpreter_identifier: str = "aws.codeinterpreter.v1"
    session_timeout_seconds: int = 900
    session_name: str | None = None
    # Optional list of dicts matching AWS filesystemConfigurations shape:
    #   [{"s3FilesConfiguration": {"accessPointArn", "fileSystemArn", "mountPath"}}]
    # or {"efsConfiguration": {...}}. Passed straight through to
    # start_code_interpreter_session. Requires the code interpreter to be
    # created with networkMode=VPC + an execution role with the mount IAM
    # permissions. See docs/agentcore-filesystem.md.
    filesystem_configurations: list[dict] | None = None


@dataclass
class AwsCodeInterpreter(CodeInterpreterSession):
    config: AwsConfig
    _client: Any = field(default=None, init=False)
    _session_id: str = field(default_factory=lambda: f"aws-{uuid4().hex[:12]}")
    _remote_id: str | None = field(default=None, init=False)
    _invoke_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._client = boto3.client("bedrock-agentcore", region_name=self.config.region)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def runtime(self) -> str:
        return "code-interpreter"

    async def start(self) -> None:
        kwargs: dict[str, Any] = dict(
            codeInterpreterIdentifier=self.config.code_interpreter_identifier,
            name=self.config.session_name or self._session_id,
            sessionTimeoutSeconds=self.config.session_timeout_seconds,
        )
        if self.config.filesystem_configurations:
            kwargs["filesystemConfigurations"] = self.config.filesystem_configurations
        resp = await asyncio.to_thread(
            self._client.start_code_interpreter_session, **kwargs
        )
        self._remote_id = resp["sessionId"]

    async def stop(self) -> None:
        if not self._remote_id:
            return
        try:
            await asyncio.to_thread(
                self._client.stop_code_interpreter_session,
                codeInterpreterIdentifier=self.config.code_interpreter_identifier,
                sessionId=self._remote_id,
            )
        finally:
            self._remote_id = None

    # --- tool surface ---

    async def execute_code(
        self,
        code: str,
        language: Language = "python",
        clear_context: bool = False,
    ) -> ExecResult:
        args: dict = {"code": code, "language": language}
        if clear_context:
            args["clearContext"] = True
        return await self._invoke("executeCode", args)

    async def execute_command(self, command: str) -> ExecResult:
        return await self._invoke("executeCommand", {"command": command})

    async def start_command_execution(self, command: str) -> str:
        stream = await self._invoke_raw("startCommandExecution", {"command": command})
        for event in stream:
            r = event.get("result") or {}
            struct = r.get("structuredContent") or {}
            if "taskId" in struct:
                return str(struct["taskId"])
        raise RuntimeError("startCommandExecution returned no taskId")

    async def get_task(self, task_id: str) -> Task:
        stream = await self._invoke_raw("getTask", {"taskId": task_id})
        return _parse_task(task_id, stream)

    async def stop_task(self, task_id: str) -> None:
        await self._invoke_raw("stopTask", {"taskId": task_id})

    async def wait_task(
        self,
        task_id: str,
        timeout_s: float = 60.0,
        initial_interval_s: float = 1.0,
        max_interval_s: float = 8.0,
    ) -> Task:
        deadline = asyncio.get_event_loop().time() + timeout_s
        interval = max(0.1, initial_interval_s)
        last: Task | None = None
        while True:
            last = await self.get_task(task_id)
            if last.status in ("succeeded", "failed", "cancelled"):
                return last
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return last
            await asyncio.sleep(min(interval, remaining))
            interval = min(max_interval_s, interval * 2)

    # --- internals ---

    async def _invoke_raw(self, name: str, arguments: dict) -> list[dict]:
        if not self._remote_id:
            raise RuntimeError("session not started")

        def _call() -> list[dict]:
            resp = self._client.invoke_code_interpreter(
                codeInterpreterIdentifier=self.config.code_interpreter_identifier,
                sessionId=self._remote_id,
                name=name,
                arguments=arguments,
            )
            return list(resp["stream"])

        async with self._invoke_lock:
            return await asyncio.to_thread(_call)

    async def _invoke(self, name: str, arguments: dict) -> ExecResult:
        stream = await self._invoke_raw(name, arguments)
        return _parse_exec(stream)


def _parse_exec(stream: list[dict]) -> ExecResult:
    stdout = ""
    stderr = ""
    exit_code = 0
    exec_ms = 0
    for event in stream:
        if "result" in event:
            r = event["result"] or {}
            struct = r.get("structuredContent") or {}
            stdout = str(struct.get("stdout", "") or "")
            stderr = str(struct.get("stderr", "") or "")
            exit_code = int(struct.get("exitCode", 0) or 0)
            exec_ms = int(float(struct.get("executionTime", 0.0)) * 1000)
            if r.get("isError") and exit_code == 0:
                exit_code = 1
            break
        for k in event:
            if "Exception" in k or k.endswith("Error"):
                msg = (event[k] or {}).get("message", k)
                return ExecResult(stdout="", stderr=msg, exit_code=1)
    return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, execution_time_ms=exec_ms)


# --- adapter registration ---

from code_interpreter.registry import StorageBinding, register  # noqa: E402


def _build_aws(storage: StorageBinding, spec) -> "AwsCodeInterpreter":
    return AwsCodeInterpreter(
        config=AwsConfig(
            region=spec.get("region", storage.region),
            code_interpreter_identifier=spec.get(
                "code_interpreter_identifier", "aws.codeinterpreter.v1"
            ),
            session_timeout_seconds=int(spec.get("session_timeout_seconds", 900)),
            filesystem_configurations=spec.get("filesystem_configurations"),
        )
    )


register("code-interpreter", _build_aws)


def _parse_task(task_id: str, stream: list[dict]) -> Task:
    for event in stream:
        if "result" in event:
            r = event["result"] or {}
            struct = r.get("structuredContent") or {}
            status = str(struct.get("taskStatus", "running")).lower()
            if status not in ("pending", "running", "succeeded", "failed", "cancelled"):
                status = "running"
            return Task(
                task_id=task_id,
                status=status,  # type: ignore[arg-type]
                stdout=str(struct.get("stdout", "") or ""),
                stderr=str(struct.get("stderr", "") or ""),
                exit_code=int(struct["exitCode"]) if "exitCode" in struct else None,
                execution_time_ms=int(float(struct.get("executionTime", 0.0)) * 1000),
            )
    return Task(task_id=task_id, status="failed", stderr="no result")
