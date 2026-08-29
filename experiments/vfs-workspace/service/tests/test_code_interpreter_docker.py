"""DockerCodeInterpreter — failure paths (no docker daemon needed)."""

import asyncio

import pytest

from code_interpreter.docker import DockerCodeInterpreter, DockerConfig


@pytest.mark.asyncio
async def test_execute_before_start_raises():
    ci = DockerCodeInterpreter(config=DockerConfig(s3_bucket="b", s3_prefix="p"))
    with pytest.raises(RuntimeError, match="session not started"):
        await ci.execute_command("echo hi")


@pytest.mark.asyncio
async def test_session_id_and_runtime_labels():
    ci = DockerCodeInterpreter(config=DockerConfig(s3_bucket="b", s3_prefix="p"))
    assert ci.session_id
    assert ci.runtime == "docker-local"
