"""Minimal test — code-interpreter engine parses AgentCore stream events (mocked boto)."""

from unittest.mock import MagicMock, patch

import pytest

from mirage.runtime.types import RunArgs

from mirage_runtimes.code_interpreter import CodeInterpreterConfig, CodeInterpreterEngine


@pytest.fixture
def cfg():
    return CodeInterpreterConfig(
        region="us-east-1",
        code_interpreter_identifier="aws.codeinterpreter.v1",
    )


@pytest.mark.asyncio
async def test_open_run_close(cfg):
    with patch("mirage_runtimes.code_interpreter.engine.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.start_code_interpreter_session.return_value = {"sessionId": "s-123"}
        client.invoke_code_interpreter.return_value = {
            "sessionId": "s-123",
            "stream": iter([
                {"result": {
                    "structuredContent": {
                        "stdout": "42\n", "stderr": "", "exitCode": 0,
                    },
                    "isError": False,
                }},
            ]),
        }

        engine = CodeInterpreterEngine(cfg)
        engine.open()
        assert client.start_code_interpreter_session.called

        result = await engine.run(RunArgs(code="print(6*7)"))
        assert result.exit_code == 0
        assert result.stdout == b"42\n"

        engine.close()
        client.stop_code_interpreter_session.assert_called_once()


@pytest.mark.asyncio
async def test_stream_error_becomes_nonzero(cfg):
    with patch("mirage_runtimes.code_interpreter.engine.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.start_code_interpreter_session.return_value = {"sessionId": "s-1"}
        client.invoke_code_interpreter.return_value = {
            "sessionId": "s-1",
            "stream": iter([
                {"validationException": {"message": "bad code"}},
            ]),
        }

        engine = CodeInterpreterEngine(cfg)
        engine.open()
        result = await engine.run(RunArgs(code="1/0"))
        assert result.exit_code == 1
        assert b"bad code" in (result.stderr or b"")
