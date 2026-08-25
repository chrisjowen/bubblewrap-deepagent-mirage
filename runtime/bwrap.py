"""Bubblewrap-in-Docker sandbox backend for deepagents.

Extends `LocalShellBackend` so file operations still hit the host workspace
directly (fast, no round-trip through Docker), but `execute()` runs the
shell command inside a Debian container wrapped by `bwrap`.

Requires Docker on the host and a prebuilt image tagged `IMAGE_TAG` below.
Build it once with:

    docker build -t bwrap-runtime runtime/
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from deepagents.backends.local_shell import (
    DEFAULT_EXECUTE_TIMEOUT,
    LocalShellBackend,
)
from deepagents.backends.protocol import ExecuteResponse

IMAGE_TAG = "bwrap-runtime"
CONTAINER_WORKDIR = "/work"

BWRAP_CMD = [
    "bwrap",
    "--bind", CONTAINER_WORKDIR, CONTAINER_WORKDIR,
    "--ro-bind", "/usr", "/usr",
    "--ro-bind", "/bin", "/bin",
    "--ro-bind-try", "/lib", "/lib",
    "--ro-bind-try", "/lib64", "/lib64",
    "--ro-bind", "/etc", "/etc",
    "--proc", "/proc",
    "--dev", "/dev",
    "--tmpfs", "/tmp",
    "--chdir", CONTAINER_WORKDIR,
    "--unshare-all",
    "--share-net",
    "--die-with-parent",
    "--setenv", "HOME", CONTAINER_WORKDIR,
    "--setenv", "PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
]


class BwrapBackend(LocalShellBackend):
    """LocalShellBackend that runs `execute` inside bwrap-in-Docker.

    Filesystem methods (`read`/`write`/`ls`/...) are inherited and touch the
    host `root_dir` directly. The same directory is bind-mounted into the
    container so shell commands see identical contents.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        image: str = IMAGE_TAG,
        timeout: int = DEFAULT_EXECUTE_TIMEOUT,
        share_net: bool = True,
        docker_bin: str | None = None,
    ) -> None:
        resolved_root = Path(root_dir).expanduser().resolve()
        resolved_root.mkdir(parents=True, exist_ok=True)
        super().__init__(root_dir=str(resolved_root), timeout=timeout)
        self._image = image
        self._share_net = share_net
        self._docker = docker_bin or shutil.which("docker")
        if self._docker is None:
            msg = "docker binary not found on PATH; install Docker Desktop or set docker_bin"
            raise RuntimeError(msg)

    def _bwrap_argv(self) -> list[str]:
        argv = list(BWRAP_CMD)
        if not self._share_net:
            argv[argv.index("--share-net")] = "--unshare-net"
        return argv

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        if not command or not isinstance(command, str):
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout <= 0:
            msg = f"timeout must be positive, got {effective_timeout}"
            raise ValueError(msg)

        docker_argv = [
            self._docker, "run", "--rm", "--privileged",
            "-v", f"{self.cwd}:{CONTAINER_WORKDIR}",
            "-w", CONTAINER_WORKDIR,
            self._image,
            *self._bwrap_argv(),
            "bash", "-c", command,
        ]

        try:
            result = subprocess.run(
                docker_argv,
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: Command timed out after {effective_timeout} seconds.",
                exit_code=124,
                truncated=False,
            )
        except Exception as exc:  # noqa: BLE001
            return ExecuteResponse(
                output=f"Error executing command ({type(exc).__name__}): {exc}",
                exit_code=1,
                truncated=False,
            )

        parts: list[str] = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.extend(f"[stderr] {line}" for line in result.stderr.strip().split("\n"))
        output = "\n".join(parts) if parts else "<no output>"

        truncated = False
        if len(output) > self._max_output_bytes:
            output = output[: self._max_output_bytes] + f"\n\n... Output truncated at {self._max_output_bytes} bytes."
            truncated = True

        if result.returncode != 0:
            output = f"{output.rstrip()}\n\nExit code: {result.returncode}"

        return ExecuteResponse(
            output=output,
            exit_code=result.returncode,
            truncated=truncated,
        )
