from __future__ import annotations

import asyncio
import os
import subprocess
import time
from uuid import uuid4

from mirage.runtime.types import RunArgs, RunResult

from mirage_runtimes.docker_local.config import DockerLocalConfig


_AWS_ENV_KEYS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
)


def _aws_env_from_host() -> dict[str, str]:
    return {k: os.environ[k] for k in _AWS_ENV_KEYS if k in os.environ}


class DockerLocalEngine:
    """One long-lived container per workspace. Shared by python + js subclasses."""

    def __init__(self, config: DockerLocalConfig) -> None:
        self._config = config
        self._container_name = f"mirage-ws-{uuid4().hex[:8]}"
        self._started = False

    @property
    def container_name(self) -> str:
        return self._container_name

    def start(self) -> None:
        env_flags: list[str] = [
            "-e", f"S3_BUCKET={self._config.s3_bucket}",
            "-e", f"S3_PREFIX={self._config.s3_prefix}",
        ]
        if self._config.aws_env_forwarding:
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
            self._config.image,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"docker run failed: {result.stderr.strip() or result.stdout.strip()}")

        deadline = time.monotonic() + self._config.startup_timeout_seconds
        while time.monotonic() < deadline:
            check = subprocess.run(
                ["docker", "exec", self._container_name,
                 "mountpoint", "-q", self._config.mount_dir],
                capture_output=True,
            )
            if check.returncode == 0:
                self._started = True
                return
            time.sleep(0.25)

        self.stop()
        raise RuntimeError(
            f"mount at {self._config.mount_dir} did not become live within "
            f"{self._config.startup_timeout_seconds}s"
        )

    async def run(self, interpreter: str, args: RunArgs) -> RunResult:
        if not self._started:
            raise RuntimeError("engine not started")

        env_flags: list[str] = []
        for k, v in args.env.items():
            env_flags.extend(["-e", f"{k}={v}"])

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", *env_flags, self._container_name,
            interpreter, "-c", args.code, *args.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate(input=args.stdin)
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise

        return RunResult(
            stdout=stdout,
            stderr=stderr or None,
            exit_code=proc.returncode if proc.returncode is not None else 1,
        )

    def stop(self) -> None:
        if not self._container_name:
            return
        subprocess.run(
            ["docker", "stop", "-t", "5", self._container_name],
            capture_output=True, timeout=15,
        )
        self._started = False
