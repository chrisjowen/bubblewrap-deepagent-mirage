"""Minimal test — docker-local engine failure path (no docker daemon needed)."""

import subprocess

import pytest

from mirage_runtimes.docker_local import DockerLocalConfig, DockerLocalEngine


def test_start_raises_on_docker_failure(monkeypatch):
    from mirage_runtimes.docker_local import engine as eng

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(eng.subprocess, "run", fake_run)

    e = DockerLocalEngine(DockerLocalConfig(s3_bucket="b", s3_prefix="p"))
    with pytest.raises(RuntimeError, match="docker run failed: boom"):
        e.start()


def test_container_name_stable_across_calls():
    e = DockerLocalEngine(DockerLocalConfig(s3_bucket="b", s3_prefix="p"))
    name = e.container_name
    assert name.startswith("mirage-ws-")
    assert e.container_name == name  # idempotent read
