"""AwsCodeInterpreter — parses AgentCore invoke_code_interpreter stream (mocked boto3)."""

from unittest.mock import MagicMock, patch

import pytest

from code_interpreter.aws import AwsCodeInterpreter, AwsConfig


@pytest.fixture
def cfg():
    return AwsConfig(region="us-east-1", code_interpreter_identifier="aws.codeinterpreter.v1")


@pytest.mark.asyncio
async def test_execute_code_happy_path(cfg):
    with patch("code_interpreter.aws.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.start_code_interpreter_session.return_value = {"sessionId": "s-1"}
        client.invoke_code_interpreter.return_value = {
            "sessionId": "s-1",
            "stream": iter([
                {"result": {
                    "structuredContent": {"stdout": "42\n", "stderr": "", "exitCode": 0},
                    "isError": False,
                }},
            ]),
        }

        ci = AwsCodeInterpreter(config=cfg)
        await ci.start()
        result = await ci.execute_code("print(6*7)")
        assert result.exit_code == 0
        assert result.stdout == "42\n"
        await ci.stop()
        client.stop_code_interpreter_session.assert_called_once()


@pytest.mark.asyncio
async def test_exception_event_becomes_nonzero(cfg):
    with patch("code_interpreter.aws.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.start_code_interpreter_session.return_value = {"sessionId": "s-1"}
        client.invoke_code_interpreter.return_value = {
            "sessionId": "s-1",
            "stream": iter([
                {"validationException": {"message": "bad code"}},
            ]),
        }
        ci = AwsCodeInterpreter(config=cfg)
        await ci.start()
        result = await ci.execute_code("1/0")
        assert result.exit_code == 1
        assert "bad code" in result.stderr


@pytest.mark.asyncio
async def test_start_command_execution_returns_task_id(cfg):
    with patch("code_interpreter.aws.boto3") as boto_mod:
        client = MagicMock()
        boto_mod.client.return_value = client
        client.start_code_interpreter_session.return_value = {"sessionId": "s-1"}
        client.invoke_code_interpreter.return_value = {
            "sessionId": "s-1",
            "stream": iter([
                {"result": {"structuredContent": {"taskId": "t-1"}}},
            ]),
        }
        ci = AwsCodeInterpreter(config=cfg)
        await ci.start()
        assert await ci.start_command_execution("sleep 10") == "t-1"
