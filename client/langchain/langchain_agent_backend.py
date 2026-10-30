"""
LangChain / LangGraph agent backend.

Wraps a LangGraph agent (created via langchain.agents.create_agent) and
translates its LangGraph-specific streaming format into the common
ThinkingChunk / FinalChunk protocol.
"""
from typing import AsyncIterator

from client.agent_backend import (
    AgentBackend,
    AgentChunk,
    FinalChunk,
    ThinkingChunk,
    ToolCallChunk,
    ToolResultChunk,
    extract_final_response,
)
from client.constants import FINAL_RESPONSE_MARKER
from client.mcp_apps import model_dump_json


class LangChainAgentBackend(AgentBackend):
    """AgentBackend backed by a LangGraph react-agent."""

    def __init__(self, agent):
        self._agent = agent

    async def astream(self, question: str) -> AsyncIterator[AgentChunk]:
        last_values = None
        inputs = {"messages": [{"role": "user", "content": question}]}

        async for mode, payload in self._agent.astream(
            inputs, stream_mode=["updates", "values"]
        ):
            if mode == "values":
                last_values = payload
                continue
            for event in self._structured_tool_events(payload):
                yield event
            if line := self._format_stream_update(payload):
                yield ThinkingChunk(content=line)

        response, thinking = LangChainAgentBackend._extract_final_response_and_thinking(last_values or {})
        yield FinalChunk(response=response, success=True, thinking=thinking)

    @staticmethod
    def _value(message, name: str, default=None):
        return message.get(name, default) if isinstance(message, dict) else getattr(message, name, default)

    @staticmethod
    def _mcp_content(content) -> list[dict]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if not isinstance(content, list):
            return []
        converted = []
        for item in content:
            item = model_dump_json(item)
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image" and "base64" in item:
                converted.append({
                    "type": "image",
                    "data": item["base64"],
                    "mimeType": item.get("mime_type", "image/png"),
                })
            else:
                converted.append(item)
        return converted

    @classmethod
    def _structured_tool_events(cls, update):
        states = update.values() if isinstance(update, dict) else []
        for state in states:
            if not isinstance(state, dict):
                continue
            for message in state.get("messages") or []:
                for call in cls._value(message, "tool_calls", []) or []:
                    call_id = cls._value(call, "id")
                    name = cls._value(call, "name")
                    if call_id and name:
                        yield ToolCallChunk(
                            tool_call_id=str(call_id),
                            name=str(name),
                            arguments=cls._value(call, "args", {}) or {},
                        )
                call_id = cls._value(message, "tool_call_id")
                if not call_id:
                    continue
                artifact = cls._value(message, "artifact") or {}
                if hasattr(artifact, "model_dump"):
                    artifact = artifact.model_dump()
                structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
                meta = (artifact.get("_meta") or artifact.get("meta")) if isinstance(artifact, dict) else None
                yield ToolResultChunk(
                    tool_call_id=str(call_id),
                    content=cls._mcp_content(cls._value(message, "content")),
                    structured_content=model_dump_json(structured),
                    is_error=cls._value(message, "status") == "error",
                    meta=model_dump_json(meta),
                )

    @staticmethod
    def _format_stream_update(update_dict) -> str | None:
        """Convert a single LangGraph stream update into a human-readable line."""
        lines = []
        for node_name, state in (update_dict.items() if isinstance(update_dict, dict) else []):
            if not isinstance(state, dict):
                continue
            messages = state.get("messages") or []
            for msg in messages:
                content = LangChainAgentBackend._value(msg, "content")
                if content:
                    content = str(content).strip()
                if not content:
                    if hasattr(msg, "tool_calls") and getattr(msg, "tool_calls", None):
                        for tc in msg.tool_calls or []:
                            name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                            lines.append(f"[{node_name}] Calling tool: {name} with args: {args}")
                    elif isinstance(msg, dict) and msg.get("tool_calls"):
                        for tc in msg["tool_calls"] or []:
                            lines.append(f"[{node_name}] Calling tool: {tc.get('name', '?')} with args: {tc.get('args', {})}")
                    continue
                msg_type = (
                    getattr(msg, "type", "")
                    if hasattr(msg, "type")
                    else (msg.get("type") if isinstance(msg, dict) else "")
                )
                is_tool = (
                    "tool" in str(msg_type).lower()
                    or (hasattr(msg, "tool_call_id") and getattr(msg, "tool_call_id", None))
                    or (isinstance(msg, dict) and msg.get("tool_call_id"))
                )
                truncated = content[:500] + ("..." if len(content) > 500 else "")
                if is_tool:
                    lines.append(f"[{node_name}] Tool result: {truncated}")
                else:
                    lines.append(f"[{node_name}] {truncated}")
        return "\n".join(lines) if lines else None

    @staticmethod
    def _extract_final_response_and_thinking(state: dict) -> tuple[str, str]:
        """Extract final response and thinking summary from a LangGraph graph state."""
        if not state or not isinstance(state, dict):
            return "Response received but content was empty", ""

        messages = state.get("messages") or []
        all_content: list[str] = []
        thinking_content: list[str] = []

        for i, message in enumerate(messages):
            if hasattr(message, "content") and message.content:
                content_str = str(message.content).strip()
                if not content_str:
                    continue
                all_content.append(content_str)
                msg_type = getattr(message, "type", "")
                if msg_type in ("tool", "tool_use") or "tool" in content_str.lower():
                    thinking_content.append(f"Tool: {content_str}")
                elif i == 0:
                    thinking_content.append(f"User: {content_str}")
                elif i < len(messages) - 1:
                    thinking_content.append(f"Agent: {content_str}")

        thinking = "\n\n".join(thinking_content) if thinking_content else "Agent processed the request"

        final_response: str | None = None
        for content in all_content:
            if FINAL_RESPONSE_MARKER in content:
                final_response = extract_final_response(content)
                break
        if not final_response:
            for content in reversed(all_content):
                if not any(w in content.lower() for w in ("tool", "function", "action:", "observation:")):
                    final_response = content
                    break
        if not final_response and all_content:
            final_response = all_content[-1]

        return final_response or "Response received but content was empty", thinking
