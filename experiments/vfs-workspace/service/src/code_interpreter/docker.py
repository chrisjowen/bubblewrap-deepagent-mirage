"""Local Docker implementation of CodeInterpreterSession.

Spawns a mirage-runtime container per session, mounts S3 at /workspace
via mountpoint-s3 (baked into the image). Every tool call dispatches
through `docker exec`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass, field
from uuid import uuid4

from code_interpreter.protocol import (
    CodeInterpreterSession,
    ExecResult,
    Language,
    Task,
    TaskStatus,
)


_AWS_ENV_KEYS = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
)


def _aws_env_from_host() -> dict[str, str]:
    return {k: os.environ[k] for k in _AWS_ENV_KEYS if k in os.environ}


@dataclass
class DockerConfig:
    s3_bucket: str
    s3_prefix: str
    image: str = "mirage-runtime:latest"
    aws_env_forwarding: bool = True
    startup_timeout_seconds: float = 15.0
    mount_dir: str = "/workspace"


@dataclass
class _RunningTask:
    task_id: str
    process: asyncio.subprocess.Process
    started_at: float
    stdout: bytes = b""
    stderr: bytes = b""
    status: TaskStatus = "running"


@dataclass
class DockerCodeInterpreter(CodeInterpreterSession):
    config: DockerConfig
    _session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    _container_name: str = ""
    _started: bool = False
    _tasks: dict[str, _RunningTask] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._container_name = f"mirage-ws-{self._session_id}"

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def runtime(self) -> str:
        return "docker-local"

    async def start(self) -> None:
        env_flags: list[str] = [
            "-e", f"S3_BUCKET={self.config.s3_bucket}",
            "-e", f"S3_PREFIX={self.config.s3_prefix}",
        ]
        if self.config.aws_env_forwarding:
            for k, v in _aws_env_from_host().items():
                env_flags.extend(["-e", f"{k}={v}"])

        vol_flags: list[str] = []
        home_aws = os.path.expanduser("~/.aws")
        if os.path.isdir(home_aws):
            vol_flags.extend(["-v", f"{home_aws}:/root/.aws:ro"])

        cmd = [
            "docker", "run", "-d", "--rm",
            "--name", self._container_name,
            "--cap-add", "SYS_ADMIN",
            "--device", "/dev/fuse",
            "--security-opt", "apparmor:unconfined",
            *env_flags,
            *vol_flags,
            self.config.image,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker run failed: {err.decode(errors='replace').strip()}")

        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while time.monotonic() < deadline:
            check = await asyncio.create_subprocess_exec(
                "docker", "exec", self._container_name,
                "mountpoint", "-q", self.config.mount_dir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await check.wait()
            if check.returncode == 0:
                self._started = True
                return
            await asyncio.sleep(0.25)

        await self.stop()
        raise RuntimeError(
            f"mount at {self.config.mount_dir} did not become live within "
            f"{self.config.startup_timeout_seconds}s"
        )

    async def stop(self) -> None:
        for t in list(self._tasks.values()):
            try:
                t.process.kill()
            except Exception:
                pass
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "-t", "5", self._container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=15)
        except Exception:
            subprocess.run(
                ["docker", "kill", self._container_name],
                capture_output=True, timeout=10,
            )
        finally:
            self._started = False

    # --- tool surface ---

    async def execute_code(
        self,
        code: str,
        language: Language = "python",
        clear_context: bool = False,  # noqa: ARG002 - docker sandbox has no persistent kernel
    ) -> ExecResult:
        interpreter = {"python": "python3", "node": "node", "bash": "bash"}[language]
        return await self._exec([interpreter, "-c", code])

    async def execute_command(self, command: str) -> ExecResult:
        return await self._exec(["bash", "-c", command])

    async def start_command_execution(self, command: str) -> str:
        if not self._started:
            raise RuntimeError("session not started")
        task_id = f"task-{uuid4().hex[:12]}"
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", self._container_name, "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        task = _RunningTask(task_id=task_id, process=proc, started_at=time.monotonic())
        self._tasks[task_id] = task
        asyncio.create_task(self._reap(task))
        return task_id

    async def _reap(self, task: _RunningTask) -> None:
        stdout, stderr = await task.process.communicate()
        task.stdout = stdout
        task.stderr = stderr
        if task.status == "cancelled":
            return
        task.status = "succeeded" if task.process.returncode == 0 else "failed"

    async def get_task(self, task_id: str) -> Task:
        t = self._tasks.get(task_id)
        if t is None:
            return Task(task_id=task_id, status="failed", stderr="unknown task_id")
        return Task(
            task_id=t.task_id,
            status=t.status,
            stdout=t.stdout.decode("utf-8", errors="replace"),
            stderr=t.stderr.decode("utf-8", errors="replace"),
            exit_code=t.process.returncode,
            execution_time_ms=int((time.monotonic() - t.started_at) * 1000),
        )

    async def stop_task(self, task_id: str) -> None:
        t = self._tasks.get(task_id)
        if t is None or t.status != "running":
            return
        t.status = "cancelled"
        try:
            t.process.kill()
        except Exception:
            pass

    # --- internals ---

    async def _exec(self, argv: list[str]) -> ExecResult:
        if not self._started:
            raise RuntimeError("session not started")
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self._container_name, *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return ExecResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else 1,
            execution_time_ms=int((time.monotonic() - started) * 1000),
        )
