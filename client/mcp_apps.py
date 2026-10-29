"""Small protocol helpers shared by the MCP Apps host backends."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final

import mcp.types as types
from mcp import ClientSession
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS


UI_EXTENSION_ID: Final = "io.modelcontextprotocol/ui"
UI_MIME_TYPE: Final = "text/html;profile=mcp-app"


class MCPAppsClientSession(ClientSession):
    """Client session that advertises MCP Apps HTML support."""

    async def initialize(self) -> types.InitializeResult:
        result = await self.send_request(
            types.ClientRequest(types.InitializeRequest(
                params=types.InitializeRequestParams(
                    protocolVersion=types.LATEST_PROTOCOL_VERSION,
                    capabilities=types.ClientCapabilities(
                        extensions={UI_EXTENSION_ID: {"mimeTypes": [UI_MIME_TYPE]}},
                        tasks=self._task_handlers.build_capability(),
                    ),
                    clientInfo=self._client_info,
                )
            )),
            types.InitializeResult,
        )
        if result.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(
                f"Unsupported protocol version from the server: {result.protocolVersion}"
            )
        self._server_capabilities = result.capabilities
        await self.send_notification(types.ClientNotification(types.InitializedNotification()))
        return result


def ui_meta(value: Any) -> dict[str, Any]:
    meta = getattr(value, "meta", None)
    value = meta.get("ui") if isinstance(meta, dict) else None
    return value if isinstance(value, dict) else {}


def app_uri(tool: Any) -> str | None:
    value = ui_meta(tool).get("resourceUri")
    return value if isinstance(value, str) else None


def model_dump_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [model_dump_json(item) for item in value]
    if isinstance(value, dict):
        return {key: model_dump_json(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class MCPToolResult:
    content: list[dict[str, Any]]
    structured_content: dict[str, Any] | None
    is_error: bool
    meta: dict[str, Any] | None = None

    @classmethod
    def from_mcp(cls, result: types.CallToolResult) -> "MCPToolResult":
        return cls(
            content=[model_dump_json(item) for item in result.content],
            structured_content=model_dump_json(result.structuredContent),
            is_error=result.isError,
            meta=model_dump_json(result.meta),
        )

    def text_for_model(self) -> str:
        text = [
            item.get("text", "")
            for item in self.content
            if item.get("type") == "text" and item.get("text")
        ]
        if text:
            return "\n".join(text)
        return str(self.structured_content) if self.structured_content is not None else "(no output)"


def serialize_app_resource(
    result: types.ReadResourceResult,
    requested_uri: str,
    listing_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for resource in result.contents:
        if str(resource.uri) != requested_uri:
            continue
        if resource.mimeType != UI_MIME_TYPE:
            raise ValueError(f"Expected {UI_MIME_TYPE!r}, got {resource.mimeType!r}")
        if not isinstance(resource, types.TextResourceContents):
            raise ValueError("MCP App resource must contain HTML text")
        return {
            "uri": requested_uri,
            "mimeType": resource.mimeType,
            "html": resource.text,
            "meta": model_dump_json(ui_meta(resource) or listing_meta or {}),
        }
    raise ValueError(f"Server did not return {requested_uri!r}")


async def run_on_loop(
    operation: Callable[[], Awaitable[Any]], owner_loop: asyncio.AbstractEventLoop
) -> Any:
    if asyncio.get_running_loop() is owner_loop:
        return await operation()
    future = asyncio.run_coroutine_threadsafe(operation(), owner_loop)
    return await asyncio.wrap_future(future)
