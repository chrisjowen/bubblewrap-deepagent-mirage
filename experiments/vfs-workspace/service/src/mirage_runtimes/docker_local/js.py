from __future__ import annotations

from typing import Any, ClassVar

from mirage.runtime.js.base import JsRuntime
from mirage.runtime.types import RunArgs, RunResult, RuntimeReach

from mirage_runtimes.docker_local.config import DockerLocalConfig
from mirage_runtimes.docker_local.engine import DockerLocalEngine


class MountLocalJs(JsRuntime):
    name = "docker-local"
    reach: RuntimeReach = "process"
    config_cls: ClassVar[type] = DockerLocalConfig
    config: DockerLocalConfig

    def __init__(
        self,
        captures=None,
        config: DockerLocalConfig | dict[str, Any] | None = None,
        script=None,
    ) -> None:
        super().__init__(captures, config, script)
        if isinstance(self.config, dict):
            self.config = DockerLocalConfig(**self.config)
        self._engine = DockerLocalEngine(self.config)
        self._engine.start()

    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run("node", args)

    def __del__(self) -> None:
        try:
            self._engine.stop()
        except Exception:
            pass
