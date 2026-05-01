"""
Agent backend abstraction.

Defines a common streaming protocol so web_ui_server.py is decoupled from
any specific LLM framework (LangChain/LangGraph or direct boto3).

Backends yield ThinkingChunk objects for intermediate reasoning steps and a
single FinalChunk when the agent has produced its final answer.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

from client.constants import FINAL_RESPONSE_MARKER


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
