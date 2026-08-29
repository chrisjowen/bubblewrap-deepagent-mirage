from __future__ import annotations

from typing import Any, ClassVar

from mirage.runtime.python.base import PythonRuntime
from mirage.runtime.types import RunArgs, RunResult, RuntimeReach

from mirage_runtimes.code_interpreter.config import CodeInterpreterConfig
from mirage_runtimes.code_interpreter.engine import CodeInterpreterEngine


class CodeInterpreterPython(PythonRuntime):
    name = "code-interpreter"
    reach: RuntimeReach = "remote"
    config_cls: ClassVar[type] = CodeInterpreterConfig
    config: CodeInterpreterConfig

    def __init__(
        self,
        captures=None,
        config: CodeInterpreterConfig | dict[str, Any] | None = None,
        script=None,
    ) -> None:
        super().__init__(captures, config, script)
        if isinstance(self.config, dict):
            self.config = CodeInterpreterConfig(**self.config)
        self._engine = CodeInterpreterEngine(self.config)
        self._engine.open()

    async def run(self, args: RunArgs) -> RunResult:
        return await self._engine.run(args)

    def __del__(self) -> None:
        try:
            self._engine.close()
        except Exception:
            pass
