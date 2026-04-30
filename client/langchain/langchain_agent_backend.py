"""
LangChain / LangGraph agent backend.

Wraps a LangGraph agent (created via langchain.agents.create_agent) and
translates its LangGraph-specific streaming format into the common
ThinkingChunk / FinalChunk protocol.
"""
from typing import AsyncIterator

from client.agent_backend import AgentBackend, AgentChunk, ThinkingChunk, FinalChunk, extract_final_response
from client.constants import FINAL_RESPONSE_MARKER


class LangChainAgentBackend(AgentBackend):
    """AgentBackend backed by a LangGraph react-agent."""

    def __init__(self, agent):
        self._agent = agent

    async def astream(self, question: str) -> AsyncIterator[AgentChunk]:
        last_values = None
        thinking_lines: list[str] = []
        inputs = {"messages": [{"role": "user", "content": question}]}

        async for chunk in self._agent.astream(inputs, stream_mode=["updates", "values"]):
            if isinstance(chunk, tuple) and len(chunk) == 2:
                mode, payload = chunk
                if mode == "values":
                    last_values = payload
                elif mode == "updates":
                    line = LangChainAgentBackend._format_stream_update(payload)
                    if line:
                        thinking_lines.append(line)
                        yield ThinkingChunk(content=line)
            elif isinstance(chunk, dict):
                if "messages" in chunk and not any(k in chunk for k in ("model", "tools")):
                    last_values = chunk
                else:
                    line = LangChainAgentBackend._format_stream_update(chunk)
                    if line:
                        thinking_lines.append(line)
                        yield ThinkingChunk(content=line)

        response, thinking = LangChainAgentBackend._extract_final_response_and_thinking(last_values or {})
        yield FinalChunk(response=response, success=True, thinking=thinking)

    @staticmethod
    def _msg_content(msg):
        if hasattr(msg, "content"):
            return getattr(msg, "content", None)
        if isinstance(msg, dict):
            return msg.get("content")
        return None

    @staticmethod
    def _format_stream_update(update_dict) -> str | None:
        """Convert a single LangGraph stream update into a human-readable line."""
        lines = []
        for node_name, state in (update_dict.items() if isinstance(update_dict, dict) else []):
            if not isinstance(state, dict):
                continue
            messages = state.get("messages") or []
            for msg in messages:
                content = LangChainAgentBackend._msg_content(msg)
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
