"""LangChain MCP backend with MCP Apps support."""
from langchain.agents import create_agent as create_lc_agent
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool

from client.agent_backend import AgentBackend
from client.langchain.langchain_agent_backend import LangChainAgentBackend
from client.llm_provider import LLM_PROVIDER, get_llm_provider
from client.mcp_client_backend import MCPClientBackend
from client.messages import SYSTEM_PROMPT


class _SessionProxy:
    def __init__(self, backend: "LangChainMCPClientBackend") -> None:
        self._backend = backend

    async def call_tool(self, name: str, arguments: dict, **_kwargs):
        return await self._backend._call_tool(name, arguments)


class LangChainMCPClientBackend(MCPClientBackend):
    def _convert_tools(self, tools: list) -> list:
        proxy = _SessionProxy(self)
        return [
            convert_mcp_tool_to_langchain_tool(proxy, tool)
            for tool in tools
        ]

    def create_agent(self, verbose: bool = False) -> AgentBackend:
        agent = create_lc_agent(
            get_llm_provider(), self._tools, system_prompt=SYSTEM_PROMPT, debug=verbose
        )
        print(f"Using LangChainAgentBackend with provider '{LLM_PROVIDER}'")
        return LangChainAgentBackend(agent)

    async def _call_tool(self, name: str, arguments: dict):
        return await self._on_owner_loop(lambda: self._session.call_tool(name, arguments))
