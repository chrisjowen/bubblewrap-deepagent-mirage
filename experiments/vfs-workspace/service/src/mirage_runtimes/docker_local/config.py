from dataclasses import dataclass

from mirage.runtime.config import RuntimeConfig


@dataclass(frozen=True, slots=True)
class DockerLocalConfig(RuntimeConfig):
    s3_bucket: str = ""
    s3_prefix: str = ""
    image: str = "mirage-runtime:latest"
    aws_env_forwarding: bool = True
    startup_timeout_seconds: float = 15.0
    mount_dir: str = "/workspace"
