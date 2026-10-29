import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcp import types

from client.langchain.langchain_agent_backend import LangChainAgentBackend
from client.mcp_apps import (
    MCPAppsClientSession,
    UI_EXTENSION_ID,
    UI_MIME_TYPE,
    app_uri,
    serialize_app_resource,
)


class MCPAppsTests(unittest.TestCase):
    def test_resource_uri(self):
        tool = SimpleNamespace(meta={"ui": {"resourceUri": "ui://ask-vee"}})
        self.assertEqual(app_uri(tool), "ui://ask-vee")

    def test_text_resource(self):
        text = types.ReadResourceResult(contents=[types.TextResourceContents(
            uri="ui://view", mimeType=UI_MIME_TYPE, text="<html>text</html>"
        )])
        self.assertEqual(serialize_app_resource(text, "ui://view")["html"], "<html>text</html>")

    def test_tool_events_are_correlated(self):
        update = {
            "model": {"messages": [{"tool_calls": [
                {"id": "call-1", "name": "chart", "args": {"team": "Sales"}}
            ]}]},
            "tools": {"messages": [{
                "tool_call_id": "call-1",
                "content": [{"type": "text", "text": "ok"}],
                "artifact": {"structured_content": {"total": 3}},
            }]},
        }
        events = LangChainAgentBackend._structured_tool_events(update, set(), set())
        self.assertEqual(events[0].tool_call_id, "call-1")
        self.assertEqual(events[1].structured_content, {"total": 3})


class MCPAppsProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_advertises_ui_extension(self):
        session = object.__new__(MCPAppsClientSession)
        session._client_info = types.Implementation(name="test", version="1")
        session._task_handlers = SimpleNamespace(build_capability=lambda: None)
        session.send_request = AsyncMock(return_value=types.InitializeResult(
            protocolVersion=types.LATEST_PROTOCOL_VERSION,
            capabilities=types.ServerCapabilities(),
            serverInfo=types.Implementation(name="server", version="1"),
        ))
        session.send_notification = AsyncMock()
        await session.initialize()
        request = session.send_request.call_args.args[0]
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        self.assertEqual(
            payload["params"]["capabilities"]["extensions"][UI_EXTENSION_ID],
            {"mimeTypes": [UI_MIME_TYPE]},
        )


if __name__ == "__main__":
    unittest.main()
