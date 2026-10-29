"""LangChain MCP backend with MCP Apps support."""
import asyncio
import contextlib

import httpx
from langchain.agents import create_agent as create_lc_agent
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from client.agent_backend import AgentBackend
from client.langchain.langchain_agent_backend import LangChainAgentBackend
from client.llm_provider import LLM_PROVIDER, get_llm_provider
from client.mcp_apps import (
    MCPAppsClientSession,
    app_uri,
    run_on_loop,
    serialize_app_resource,
    ui_meta,
)
from client.mcp_client_backend import MCPClientBackend
from client.messages import SYSTEM_PROMPT


class _SessionProxy:
    def __init__(self, backend: "LangChainMCPClientBackend") -> None:
        self._backend = backend

    async def call_tool(self, name: str, arguments: dict, **_kwargs):
        return await self._backend._call_tool(name, arguments)


class LangChainMCPClientBackend(MCPClientBackend):
    def __init__(self, url: str, auth: httpx.Auth) -> None:
        self._url = url
        self._auth = auth
        self._session = None
        self._exit_stack = None
        self._owner_loop = None
        self._raw_tools = []
        self._tools = []
        self._prompts = []
        self._resource_meta = {}

    async def __aenter__(self) -> "LangChainMCPClientBackend":
        self._owner_loop = asyncio.get_running_loop()
        self._exit_stack = contextlib.AsyncExitStack()
        await self._exit_stack.__aenter__()
        http_client = await self._exit_stack.enter_async_context(httpx.AsyncClient(
            auth=self._auth,
            timeout=httpx.Timeout(30.0, read=None),
        ))
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(self._url, http_client=http_client)
        )
        self._session = await self._exit_stack.enter_async_context(
            MCPAppsClientSession(read, write)
        )
        await self._session.initialize()
        self._raw_tools = (await self._session.list_tools()).tools
        proxy = _SessionProxy(self)
        self._tools = [
            convert_mcp_tool_to_langchain_tool(proxy, tool)
            for tool in self._raw_tools
        ]
        self._prompts = (await self._session.list_prompts()).prompts
        if any(app_uri(tool) for tool in self._raw_tools):
            try:
                resources = (await self._session.list_resources()).resources
                self._resource_meta = {
                    str(resource.uri): ui_meta(resource)
                    for resource in resources
                    if ui_meta(resource)
                }
            except Exception:
                self._resource_meta = {}
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._exit_stack:
            await self._exit_stack.__aexit__(*exc_info)

    def tool_definitions(self) -> list[dict]:
        return [{
            "name": tool.name,
            "description": tool.description or "No description available",
            "args": tool.inputSchema.get("properties", {}),
            "args_schema": tool.inputSchema,
        } for tool in self._raw_tools]

    def app_definitions(self) -> dict[str, str]:
        return {
            tool.name: uri
            for tool in self._raw_tools
            if (uri := app_uri(tool)) is not None
        }

    @property
    def prompts(self) -> list:
        return self._prompts

    def create_agent(self, verbose: bool = False) -> AgentBackend:
        agent = create_lc_agent(
            get_llm_provider(), self._tools, system_prompt=SYSTEM_PROMPT, debug=verbose
        )
        print(f"Using LangChainAgentBackend with provider '{LLM_PROVIDER}'")
        return LangChainAgentBackend(agent)

    async def _on_owner_loop(self, operation):
        return await run_on_loop(operation, self._owner_loop)

    async def _call_tool(self, name: str, arguments: dict):
        return await self._on_owner_loop(lambda: self._session.call_tool(name, arguments))

    async def get_prompt_messages(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[str]:
        async def fetch():
            result = await self._session.get_prompt(name, arguments=arguments or {})
            return [
                message.content.text if isinstance(message.content, TextContent) else ""
                for message in result.messages
            ]
        return await self._on_owner_loop(fetch)

    async def read_app_resource(self, uri: str) -> dict:
        if uri not in self.app_definitions().values():
            raise PermissionError("The URI was not declared by an MCP App tool")
        result = await self._on_owner_loop(lambda: self._session.read_resource(uri))
        return serialize_app_resource(result, uri, self._resource_meta.get(uri))
