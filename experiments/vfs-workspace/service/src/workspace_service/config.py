from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


RuntimeName = Literal["docker-local", "code-interpreter"]


class UserSpec(BaseModel):
    s3_bucket: str
    s3_region: str
    s3_prefix: str
    runtime: RuntimeName
    mount_name: str = "disk"


class WorkspacesConfig(BaseModel):
    users: dict[str, UserSpec]
    runtimes: dict[str, dict] = {}


def load_config(path: Path) -> WorkspacesConfig:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return WorkspacesConfig.model_validate(data)
