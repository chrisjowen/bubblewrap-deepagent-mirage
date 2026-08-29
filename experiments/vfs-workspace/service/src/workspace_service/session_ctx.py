"""Contextvar carrying the caller's user_id for the current request.

Middleware in main.py sets this from the X-User-Id header on every
/mcp request (and any other route that opts in). MCP tool functions
read it to resolve which workspace / session to act on.
"""

from contextvars import ContextVar

current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
