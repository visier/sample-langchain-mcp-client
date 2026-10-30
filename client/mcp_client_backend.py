"""
MCP client backend interface and factory.

This is distinct from AgentBackend (which abstracts only the LLM loop):
MCPClientBackend also owns the MCP server connection and tool/prompt loading.

Implementations live in client/langchain/ and client/bedrock/.
"""
import asyncio
import contextlib
from abc import ABC, abstractmethod

import httpx
from mcp.client.streamable_http import streamable_http_client

from client.agent_backend import AgentBackend
from client.mcp_apps import (
    MCPAppsClientSession,
    app_uri,
    run_on_loop,
    serialize_app_resource,
)


class MCPClientBackend(ABC):
    """Manages MCP server connection, tool/prompt loading, and agent creation.

    Use as an async context manager:

        async with backend:
            agent = backend.create_agent()
            messages = await backend.get_prompt_messages("my-prompt")
    """

    def __init__(self, url: str, auth: httpx.Auth) -> None:
        self._url = url
        self._auth = auth
        self._raw_tools = []
        self._tools = []
        self._prompts = []

    async def __aenter__(self) -> "MCPClientBackend":
        self._owner_loop = asyncio.get_running_loop()
        self._exit_stack = contextlib.AsyncExitStack()
        await self._exit_stack.__aenter__()
        client = await self._exit_stack.enter_async_context(httpx.AsyncClient(
            auth=self._auth,
            headers={"User-Agent": "sample-langchain-mcp-client/0.1.0"},
            timeout=httpx.Timeout(30.0, read=None),
        ))
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(self._url, http_client=client)
        )
        self._session = await self._exit_stack.enter_async_context(
            MCPAppsClientSession(read, write)
        )
        await self._session.initialize()
        self._raw_tools = (await self._session.list_tools()).tools
        self._tools = self._convert_tools(self._raw_tools)
        self._prompts = (await self._session.list_prompts()).prompts
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._exit_stack.__aexit__(*exc_info)

    def tool_definitions(self) -> list[dict]:
        """Return UI-ready tool info dicts with name, description, args, and args_schema."""
        return [{
            "name": tool.name,
            "description": tool.description or "No description available",
            "args": tool.inputSchema.get("properties", {}),
            "args_schema": tool.inputSchema,
            "app": app_uri(tool),
        } for tool in self._raw_tools]

    def app_definitions(self) -> dict[str, str]:
        """Return UI resource URIs keyed by tool name."""
        return {
            tool.name: uri
            for tool in self._raw_tools
            if (uri := app_uri(tool)) is not None
        }

    async def read_app_resource(self, uri: str) -> dict:
        """Read and validate a declared MCP App HTML resource."""
        if uri not in self.app_definitions().values():
            raise PermissionError("The URI was not declared by an MCP App tool")
        result = await self._on_owner_loop(lambda: self._session.read_resource(uri))
        return serialize_app_resource(result, uri)

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
            for p in self._prompts
        ]

    @abstractmethod
    def create_agent(self, verbose: bool = False) -> AgentBackend:
        """Build and return the AgentBackend instance wired up to the loaded tools.

        Args:
            verbose: If True, enables debug-level logging of the agent's reasoning steps.
                     Currently only has effect for the LangChain backend.
        """
        ...

    async def get_prompt_messages(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[str]:
        """Fetch a prompt by name from the MCP server and return its messages as strings."""
        async def fetch():
            result = await self._session.get_prompt(name, arguments=arguments or {})
            return [getattr(message.content, "text", "") for message in result.messages]

        return await self._on_owner_loop(fetch)

    async def _on_owner_loop(self, operation):
        return await run_on_loop(operation, self._owner_loop)

    @abstractmethod
    def _convert_tools(self, tools: list) -> list:
        """Convert MCP tools to the agent backend's tool representation."""
        ...


def create_mcp_client_backend(
    url: str, auth: httpx.Auth, agent_backend: str = "langchain"
) -> MCPClientBackend:
    """Instantiate the correct MCPClientBackend for the given agent_backend."""
    if agent_backend == "boto3":
        from client.bedrock.bedrock_mcp_client_backend import BedrockMCPClientBackend
        return BedrockMCPClientBackend(url, auth)
    from client.langchain.langchain_mcp_client_backend import LangChainMCPClientBackend
    return LangChainMCPClientBackend(url, auth)
