"""
Bedrock MCP client backend.

Connects to the MCP server via raw mcp.ClientSession (no LangChain dependency)
and creates a boto3 Bedrock agent.
"""
import asyncio
import contextlib

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Prompt, TextContent

from client.mcp_client_backend import MCPClientBackend
from client.agent_backend import AgentBackend
from client.bedrock.bedrock_tool import BedrockTool
from client.bedrock.agent_backend import BedrockAgentBackend
from client.llm_provider import LLM_MODEL_ID, BEDROCK_REGION
from client.messages import SYSTEM_PROMPT


class BedrockMCPClientBackend(MCPClientBackend):
    """MCP client using raw mcp.ClientSession and a boto3 Bedrock agent. No LangChain dependency."""

    def __init__(self, url: str, auth: httpx.Auth) -> None:
        self._url = url
        self._auth = auth
        self._session: ClientSession | None = None
        self._exit_stack: contextlib.AsyncExitStack | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._tools: list[BedrockTool] = []
        self._prompts: list[Prompt] = []

    async def __aenter__(self) -> "BedrockMCPClientBackend":
        # Capture the event loop that owns this session. Tool invoke closures use
        # this to bridge back to the correct loop when called from a web server thread.
        self._main_loop = asyncio.get_running_loop()
        self._exit_stack = contextlib.AsyncExitStack()
        await self._exit_stack.__aenter__()
        # read=None disables the read timeout on the SSE stream. Without it, the
        # background SSE reader times out after 5s waiting for a tool response,
        # crashing the session mid-agent-loop with a ReadTimeout ExceptionGroup.
        http_client = httpx.AsyncClient(auth=self._auth, timeout=httpx.Timeout(30.0, read=None))
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(self._url, http_client=http_client)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        self._tools = [self._to_tool_def(t) for t in (await self._session.list_tools()).tools]
        self._prompts = (await self._session.list_prompts()).prompts
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._exit_stack:
            await self._exit_stack.__aexit__(*exc_info)

    def tool_definitions(self) -> list[dict]:
        return [
            {
                'name': t.name,
                'description': t.description or 'No description available',
                'args': t.schema.get('properties', {}),
                'args_schema': t.schema,
            }
            for t in self._tools
        ]

    @property
    def prompts(self) -> list[Prompt]:
        return self._prompts

    def create_agent(self, verbose: bool = False) -> AgentBackend:
        model_id = LLM_MODEL_ID or "anthropic.claude-3-5-sonnet-20241022-v2:0"
        print(f"Using BedrockAgentBackend with model {model_id}")
        return BedrockAgentBackend(
            tools=self._tools,
            model_id=model_id,
            region=BEDROCK_REGION,
            system_prompt=SYSTEM_PROMPT,
        )

    async def get_prompt_messages(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> list[str]:
        async def _fetch():
            result = await self._session.get_prompt(name, arguments=arguments or {})
            return [
                m.content.text if isinstance(m.content, TextContent) else ""
                for m in result.messages
            ]

        if asyncio.get_running_loop() is self._main_loop:
            return await _fetch()
        fut = asyncio.run_coroutine_threadsafe(_fetch(), self._main_loop)
        return await asyncio.wrap_future(fut)

    def _to_tool_def(self, tool) -> BedrockTool:
        session = self._session
        main_loop = self._main_loop
        name = tool.name

        async def invoke(args: dict) -> str:
            try:
                # ClientSession is bound to main_loop. If invoke is called from a
                # different event loop (e.g. the web server thread), bridge the call
                # via run_coroutine_threadsafe to avoid a cross-loop deadlock where
                # the response arrives on main_loop but nobody is listening there.
                if asyncio.get_running_loop() is main_loop:
                    result = await session.call_tool(name, args)
                else:
                    fut = asyncio.run_coroutine_threadsafe(
                        session.call_tool(name, args), main_loop
                    )
                    result = await asyncio.wrap_future(fut)
                parts = [c.text for c in result.content if isinstance(c, TextContent)]
                return "\n".join(parts) if parts else "(no output)"
            except Exception as exc:
                return f"Error calling tool '{name}': {exc}"

        return BedrockTool(
            name=name,
            description=tool.description or "",
            schema=tool.inputSchema,
            invoke=invoke,
        )
