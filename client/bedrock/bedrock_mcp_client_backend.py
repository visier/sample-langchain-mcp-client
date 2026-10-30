"""
Bedrock MCP client backend.

Connects to the MCP server via raw mcp.ClientSession (no LangChain dependency)
and creates a boto3 Bedrock agent.
"""
from client.mcp_client_backend import MCPClientBackend
from client.agent_backend import AgentBackend
from client.bedrock.bedrock_tool import BedrockTool
from client.bedrock.bedrock_agent_backend import BedrockAgentBackend
from client.llm_provider import BEDROCK_REGION, DEFAULT_BEDROCK_MODEL_ID, LLM_MODEL_ID
from client.messages import SYSTEM_PROMPT
from client.mcp_apps import MCPToolResult


class BedrockMCPClientBackend(MCPClientBackend):
    """MCP client using raw mcp.ClientSession and a boto3 Bedrock agent. No LangChain dependency."""

    def _convert_tools(self, tools: list) -> list[BedrockTool]:
        return [self._to_tool_def(tool) for tool in tools]

    def create_agent(self, verbose: bool = False) -> AgentBackend:
        model_id = LLM_MODEL_ID or DEFAULT_BEDROCK_MODEL_ID
        print(f"Using BedrockAgentBackend with model {model_id}")
        return BedrockAgentBackend(
            tools=self._tools,
            model_id=model_id,
            region=BEDROCK_REGION,
            system_prompt=SYSTEM_PROMPT,
        )

    def _to_tool_def(self, tool) -> BedrockTool:
        name = tool.name

        async def invoke(args: dict) -> MCPToolResult:
            try:
                result = await self._on_owner_loop(
                    lambda: self._session.call_tool(name, args)
                )
                return MCPToolResult.from_mcp(result)
            except Exception as exc:
                return MCPToolResult(
                    content=[{"type": "text", "text": f"Error calling tool '{name}': {exc}"}],
                    is_error=True,
                )

        return BedrockTool(
            name=name,
            description=tool.description or "",
            schema=tool.inputSchema,
            invoke=invoke,
        )
