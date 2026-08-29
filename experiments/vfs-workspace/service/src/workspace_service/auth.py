from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException, status

from workspace_service.config import WorkspacesConfig


def make_current_user_dep(config: WorkspacesConfig) -> Callable[..., str]:
    def _dep(x_user_id: str | None = Header(default=None)) -> str:
        if not x_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-Id header required",
            )
        if x_user_id not in config.users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="unknown user",
            )
        return x_user_id
    return _dep
