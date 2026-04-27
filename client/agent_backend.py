"""
Agent backend abstraction.

Defines a common streaming protocol so web_ui_server.py is decoupled from
any specific LLM framework (LangChain/LangGraph or direct boto3).

Backends yield ThinkingChunk objects for intermediate reasoning steps and a
single FinalChunk when the agent has produced its final answer.
"""
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import AsyncIterator

from client.constants import FINAL_RESPONSE_MARKER
from client.messages import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Tool definition – LangChain-free representation of an MCP tool
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    """Framework-agnostic description of a single MCP tool."""
    name: str
    description: str
    schema: dict
    invoke: Callable[[dict], Awaitable[str]]


# ---------------------------------------------------------------------------
# Chunk types – the common streaming protocol
# ---------------------------------------------------------------------------

@dataclass
class ThinkingChunk:
    """An intermediate reasoning step emitted while the agent is working."""
    content: str


@dataclass
class FinalChunk:
    """Terminal chunk carrying the agent's final answer."""
    response: str
    success: bool
    thinking: str = ""
    error: str | None = None


AgentChunk = ThinkingChunk | FinalChunk


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class AgentBackend(ABC):
    """Common interface for all agent backends."""

    @abstractmethod
    async def astream(self, question: str) -> AsyncIterator[AgentChunk]:
        """Stream agent chunks for *question*.

        Yields zero or more ThinkingChunks followed by exactly one FinalChunk.
        """


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def extract_final_response(text: str) -> str:
    """Return the text after the FINAL_RESPONSE_MARKER, or the full text."""
    if FINAL_RESPONSE_MARKER in text:
        return text.split(FINAL_RESPONSE_MARKER, 1)[1].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_agent_backend(
    tools: list,
    agent_backend: str = "langchain",
    verbose: bool = False,
) -> AgentBackend:
    """Instantiate the correct AgentBackend.

    Args:
        tools:         MCP tools returned by MultiServerMCPClient.get_tools().
        agent_backend: "langchain" (default) | "boto3".
                       "langchain" runs the LangGraph react-agent loop; the LLM is determined by LLM_PROVIDER.
                       "boto3" drives the Bedrock Converse API directly via the inline SDK; LLM_PROVIDER is ignored.
        verbose:       Enable verbose/debug logging in the LangChain agent (no-op for boto3).
    """
    if agent_backend == "boto3":
        from client.llm_provider import LLM_MODEL_ID, BEDROCK_REGION
        from client.langchain_agent import to_tool_definitions
        from client.bedrock_agent import BedrockAgentBackend
        model_id = LLM_MODEL_ID or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        print(f"Using boto3 BedrockAgentBackend with model {model_id}")
        return BedrockAgentBackend(
            tools=to_tool_definitions(tools),
            model_id=model_id,
            region=BEDROCK_REGION,
            system_prompt=SYSTEM_PROMPT,
        )

    from client.llm_provider import LLM_PROVIDER, get_llm_provider
    from langchain.agents import create_agent
    from client.langchain_agent import LangChainAgentBackend

    llm = get_llm_provider()
    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
    print(f"Using LangChainAgentBackend with provider '{LLM_PROVIDER}'")
    return LangChainAgentBackend(agent)
