"""
MCP client backend interface and factory.

This is distinct from AgentBackend (which abstracts only the LLM loop):
MCPClientBackend also owns the MCP server connection and tool/prompt loading.

Implementations live in client/langchain/ and client/bedrock/.
"""
from abc import ABC, abstractmethod

import httpx
from mcp.types import Prompt

from client.agent_backend import AgentBackend
from client.bedrock.bedrock_mcp_client_backend import BedrockMCPClientBackend
from client.langchain.langchain_mcp_client_backend import LangChainMCPClientBackend


class MCPClientBackend(ABC):
    """Manages MCP server connection, tool/prompt loading, and agent creation.

    Use as an async context manager:

        async with backend:
            agent = backend.create_agent()
            messages = await backend.get_prompt_messages("my-prompt")
    """

    @abstractmethod
    async def __aenter__(self) -> "MCPClientBackend": ...

    @abstractmethod
    async def __aexit__(self, *exc_info) -> None: ...

    @abstractmethod
    def tool_definitions(self) -> list[dict]:
        """Return UI-ready tool info dicts with name, description, args, and args_schema."""
        ...

    @property
    @abstractmethod
    def prompts(self) -> list[Prompt]: ...

    def prompt_definitions(self) -> list[dict]:
        """Return UI-ready prompt info dicts with name, description, and arguments schema."""
        return [
            {
                'name': p.name,
                'description': p.description or 'No description available',
                'arguments': [
                    {
                        'name': a.name,
                        'description': a.description,
                        'required': a.required,
                    }
                    for a in (p.arguments or [])
                ],
            }
            for p in self.prompts
        ]

    @abstractmethod
    def create_agent(self, verbose: bool = False) -> AgentBackend:
        """Build and return the AgentBackend instance wired up to the loaded tools.

        Args:
            verbose: If True, enables debug-level logging of the agent's reasoning steps.
                     Currently only has effect for the LangChain backend.
        """
        ...

    @abstractmethod
    async def get_prompt_messages(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[str]:
        """Fetch a prompt by name from the MCP server and return its messages as strings."""
        ...


def create_mcp_client_backend(
    url: str, auth: httpx.Auth, agent_backend: str = "langchain"
) -> MCPClientBackend:
    """Instantiate the correct MCPClientBackend for the given agent_backend."""
    if agent_backend == "boto3":
        return BedrockMCPClientBackend(url, auth)
    return LangChainMCPClientBackend(url, auth)
