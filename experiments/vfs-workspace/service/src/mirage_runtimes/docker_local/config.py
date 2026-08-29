from pydantic import BaseModel, Field


class DockerLocalConfig(BaseModel):
    s3_bucket: str
    s3_prefix: str
    image: str = "mirage-runtime:latest"
    aws_env_forwarding: bool = True
    startup_timeout_seconds: float = Field(default=15.0, gt=0)
    mount_dir: str = "/workspace"
