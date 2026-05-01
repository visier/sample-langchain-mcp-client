"""
boto3 inline Bedrock agent backend.

Drives the ReAct tool-calling loop directly against the Bedrock Converse API.
Has no LangChain dependency at all.
"""
import asyncio
from typing import AsyncIterator

import boto3

from client.agent_backend import AgentBackend, AgentChunk, ThinkingChunk, FinalChunk, extract_final_response
from client.bedrock.bedrock_tool import BedrockTool
from client.messages import SYSTEM_PROMPT


class BedrockAgentBackend(AgentBackend):
    """AgentBackend that drives the tool-calling loop with boto3 converse."""

    def __init__(
        self,
        tools: list[BedrockTool],
        model_id: str,
        region: str,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self._tools_by_name: dict[str, BedrockTool] = {t.name: t for t in tools}
        self._bedrock_tools = self._convert_tools(tools)
        self._model_id = model_id
        self._system_prompt = system_prompt
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def astream(self, question: str) -> AsyncIterator[AgentChunk]:
        """Drive the Bedrock converse loop, yielding chunks as work progresses."""
        messages: list[dict] = [
            {"role": "user", "content": [{"text": question}]}
        ]
        thinking_lines: list[str] = []

        while True:
            # boto3 is synchronous – run in a thread to avoid blocking the loop.
            response = await asyncio.to_thread(
                self._client.converse,
                modelId=self._model_id,
                system=[{"text": self._system_prompt}],
                messages=messages,
                toolConfig={"tools": self._bedrock_tools},
            )

            output_msg = response["output"]["message"]
            messages.append(output_msg)
            stop_reason = response["stopReason"]

            if stop_reason == "end_turn":
                final_text = " ".join(
                    block["text"]
                    for block in output_msg["content"]
                    if "text" in block
                )
                yield FinalChunk(
                    response=extract_final_response(final_text),
                    success=True,
                    thinking="\n\n".join(thinking_lines),
                )
                return

            if stop_reason == "tool_use":
                tool_results: list[dict] = []

                for block in output_msg["content"]:
                    if "text" in block:
                        line = f"[model] {block['text'][:500]}{'...' if len(block['text']) > 500 else ''}"
                        thinking_lines.append(line)
                        yield ThinkingChunk(content=line)

                    elif "toolUse" in block:
                        tool_name = block["toolUse"]["name"]
                        tool_input = block["toolUse"]["input"]
                        tool_use_id = block["toolUse"]["toolUseId"]

                        line = f"[tools] Calling tool: {tool_name} with args: {tool_input}"
                        thinking_lines.append(line)
                        yield ThinkingChunk(content=line)

                        result_text = await self._invoke_tool(tool_name, tool_input)

                        short = result_text[:500] + ("..." if len(result_text) > 500 else "")
                        line = f"[tools] Tool result: {short}"
                        thinking_lines.append(line)
                        yield ThinkingChunk(content=line)

                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"text": result_text}],
                            }
                        })

                messages.append({"role": "user", "content": tool_results})
                continue

            yield FinalChunk(
                response="",
                success=False,
                error=f"Unexpected stop reason from Bedrock: {stop_reason}",
                thinking="\n\n".join(thinking_lines),
            )
            return

    @staticmethod
    def _convert_tools(tools: list[BedrockTool]) -> list[dict]:
        """Convert BedrockTools to Bedrock toolSpec format."""
        return [
            {
                "toolSpec": {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {"json": tool.schema},
                }
            }
            for tool in tools
        ]

    async def _invoke_tool(self, tool_name: str, tool_input: dict) -> str:
        tool: BedrockTool | None = self._tools_by_name.get(tool_name)
        if tool is None:
            return f"Error: tool '{tool_name}' not found."
        return await tool.invoke(tool_input)
