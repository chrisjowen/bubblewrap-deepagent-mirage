from pydantic import BaseModel, Field


class CodeInterpreterConfig(BaseModel):
    region: str
    code_interpreter_identifier: str = Field(
        description="ARN or built-in ID of a code interpreter created via bedrock-agentcore-control.",
    )
    session_timeout_seconds: int = Field(default=900, gt=0)
    session_name: str | None = None
