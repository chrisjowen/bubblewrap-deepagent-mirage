"""AgentCore HTTP entrypoint. Streams LangGraph events as SSE text."""

from __future__ import annotations

from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from agent import build_agent

        _agent = build_agent()
    return _agent


def _text_from_chunk(chunk) -> str:
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


@app.entrypoint
async def handler(request, context):
    prompt = request.get("prompt")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")

    session_id = getattr(context, "session_id", None) or "default"

    agent = _get_agent()
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": prompt}]},
        version="v2",
        config={"configurable": {"thread_id": session_id}},
    ):
        if event.get("event") != "on_chat_model_stream":
            continue
        text = _text_from_chunk(event.get("data", {}).get("chunk"))
        if text:
            yield text


if __name__ == "__main__":
    app.run()
