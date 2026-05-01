from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class BedrockTool:
    """Wraps an MCP tool as a plain async callable for the Bedrock agent loop."""
    name: str
    description: str
    schema: dict
    invoke: Callable[[dict], Awaitable[str]]
