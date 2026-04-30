"""
LangChain MCP client backend.

Connects to the MCP server via MultiServerMCPClient (langchain-mcp-adapters)
and creates a LangChain/LangGraph agent.
"""
import json

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent as create_lc_agent

from client.mcp_client_backend import MCPClientBackend
from client.agent_backend import AgentBackend
from client.langchain.agent_backend import LangChainAgentBackend
from client.llm_provider import LLM_PROVIDER, get_llm_provider
from client.messages import SYSTEM_PROMPT

# MultiServerMCPClient manages multiple MCP servers in a named dictionary, so every
# subsequent call (session(), get_prompt(), etc.) needs this key to route to the right server.
_MCP_SERVER_NAME = "visier-service"


class LangChainMCPClientBackend(MCPClientBackend):
    """MCP client using MultiServerMCPClient and a LangChain/LangGraph agent."""

    def __init__(self, url: str, auth: httpx.Auth) -> None:
        self._url = url
        self._auth = auth
        self._client = None
        self._tools: list = []
        self._prompts: list = []

    async def __aenter__(self) -> "LangChainMCPClientBackend":
        self._client = MultiServerMCPClient({
            _MCP_SERVER_NAME: {
                "transport": "streamable_http",
                "url": self._url,
                "auth": self._auth,
            }
        })
        self._tools = await self._client.get_tools()
        async with self._client.session(_MCP_SERVER_NAME) as session:
            result = await session.list_prompts()
            self._prompts = result.prompts
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass  # MultiServerMCPClient manages its own session lifecycle internally

    def tool_definitions(self) -> list[dict]:
        result = []
        for tool in self._tools:
            schema = None
            if hasattr(tool, 'args_schema') and tool.args_schema:
                try:
                    schema = json.loads(json.dumps(tool.args_schema, default=str))
                except Exception:
                    schema = str(tool.args_schema)
            result.append({
                'name': tool.name,
                'description': getattr(tool, 'description', None) or 'No description available',
                'args': getattr(tool, 'args', {}),
                'args_schema': schema,
            })
        return result

    @property
    def prompts(self) -> list:
        return self._prompts

    def create_agent(self, verbose: bool = False) -> AgentBackend:
        llm = get_llm_provider()
        agent = create_lc_agent(llm, self._tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
        print(f"Using LangChainAgentBackend with provider '{LLM_PROVIDER}'")
        return LangChainAgentBackend(agent)

    async def get_prompt_messages(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[str]:
        messages = await self._client.get_prompt(_MCP_SERVER_NAME, name, arguments=arguments or {})
        return [getattr(m, "content", "") or "" for m in messages]
