import asyncio
import os
import traceback
import webbrowser
import logging
from threading import Thread

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, ProtectedResourceMetadata
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from pydantic import AnyHttpUrl
from client.llm_provider import LLM_PROVIDER, get_llm_provider, get_current_model_name
from web.web_ui_server import WebUIServer
from .messages import SYSTEM_PROMPT
from .oauth2 import OAuthPasswordGrantClientProvider

# Check for required environment variables
if (os.environ.get("VISIER_OAUTH_CLIENT_ID") is None or
    os.environ.get("VISIER_OAUTH_CLIENT_SECRET") is None or
    os.environ.get("VISIER_MCP_SERVER_URL") is None):
    raise ValueError("Please set VISIER_OAUTH_CLIENT_ID, VISIER_OAUTH_CLIENT_SECRET, and VISIER_MCP_SERVER_URL environment variables. See README for details.")

USE_PASSWORD_GRANT = (os.environ.get("VISIER_USERNAME") is not None and
                      os.environ.get("VISIER_PASSWORD") is not None)

VISIER_OAUTH_CLIENT_ID = os.environ["VISIER_OAUTH_CLIENT_ID"]
VISIER_OAUTH_CLIENT_SECRET = os.environ["VISIER_OAUTH_CLIENT_SECRET"]
VISIER_MCP_SERVER_URL = os.environ["VISIER_MCP_SERVER_URL"]
VISIER_USERNAME = os.environ.get("VISIER_USERNAME")
VISIER_PASSWORD = os.environ.get("VISIER_PASSWORD")
VISIER_TOKEN_ENDPOINT_URL = os.environ.get("VISIER_TOKEN_ENDPOINT_URL")

VERBOSE_LLM_LOGGING = os.environ.get("VERBOSE_LLM_LOGGING", "false").lower() == "false"

OAUTH_CLIENT_STATIC_METADATA = OAuthClientInformationFull(
    client_name="LangChain MCP client for Visier MCP server",
    client_id=VISIER_OAUTH_CLIENT_ID,
    client_secret=VISIER_OAUTH_CLIENT_SECRET,
    redirect_uris=["http://localhost:8000/callback"],
    grant_types=["authorization_code", "refresh_token"],
    token_endpoint_auth_method="client_secret_post"
)

# --- GLOBALS ---
captured_code = None
captured_state = None
app_agent = None
available_tools = []
ui_server = WebUIServer()

def set_captured_code(code, state):
    """Callback function to set the captured OAuth code"""
    global captured_code, captured_state
    captured_code = code
    captured_state = state

def get_agent():
    """Callback function to get the agent"""
    return app_agent

def get_server_url():
    """Callback function to get the server URL"""
    return VISIER_MCP_SERVER_URL

def get_model_name():
    """Callback function to get the current model name"""
    return f"{LLM_PROVIDER} ({get_current_model_name()})"

def get_tools():
    """Callback function to get the available tools list with full details"""
    tools_details = []
    for tool in available_tools:
        tool_info = {
            'name': tool.name,
            'description': getattr(tool, 'description', 'No description available'),
            'args': getattr(tool, 'args', {}),
            'args_schema': None
        }
        if hasattr(tool, 'args_schema') and tool.args_schema:
            try:
                if hasattr(tool.args_schema, 'model_json_schema'):
                    tool_info['args_schema'] = tool.args_schema.model_json_schema()
                elif hasattr(tool.args_schema, 'schema'):
                    tool_info['args_schema'] = tool.args_schema.schema
                else:
                    # Convert to dict if possible, otherwise stringify
                    try:
                        import json
                        if hasattr(tool.args_schema, '__dict__'):
                            tool_info['args_schema'] = json.loads(json.dumps(tool.args_schema.__dict__, default=str))
                        else:
                            tool_info['args_schema'] = json.loads(json.dumps(tool.args_schema, default=str))
                    except:
                        tool_info['args_schema'] = str(tool.args_schema)
            except:
                tool_info['args_schema'] = str(tool.args_schema)
        elif hasattr(tool, 'get_params_definition'):
            try:
                tool_info['args_schema'] = tool.get_params_definition()
            except:
                tool_info['args_schema'] = "Schema unavailable"
        tools_details.append(tool_info)

    return tools_details

ui_server.set_callbacks(set_captured_code, get_agent, get_server_url, get_model_name, get_tools)

class InMemoryTokenStorage(TokenStorage):
    def __init__(self):
        self.tokens = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return OAUTH_CLIENT_STATIC_METADATA

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info 

def start_local_server():
    ui_server.start_oauth_server()

async def automated_callback_handler() -> tuple[str, str | None]:
    """Captures code AND state to satisfy the security check."""
    Thread(target=start_local_server, daemon=True).start()
    
    print("Authenticating and fetching tools from MCP server...")
    while captured_code is None:
        await asyncio.sleep(0.1)  # Faster polling for OAuth callback
    return captured_code, captured_state

async def handle_redirect(auth_url: str) -> None:
    print(f"\n Opening browser: {auth_url}")
    webbrowser.open(auth_url)

# --- MAIN ---
async def main():
    global app_agent

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    os.environ["LANGCHAIN_VERBOSE"] = f"{VERBOSE_LLM_LOGGING}"
    
    if USE_PASSWORD_GRANT:
        print("Starting MCP client with OAuth Password Grant authentication...")
        oauth_provider = OAuthPasswordGrantClientProvider(
            server_url=VISIER_MCP_SERVER_URL,
            username=VISIER_USERNAME,
            password=VISIER_PASSWORD,
            client_id=OAUTH_CLIENT_STATIC_METADATA.client_id,
            client_secret=OAUTH_CLIENT_STATIC_METADATA.client_secret,
            storage=InMemoryTokenStorage(),
            token_endpoint_url=VISIER_TOKEN_ENDPOINT_URL
        )
    else:
        print("Starting MCP client with OAuth Authorization Code Grant authentication...")
        oauth_provider = OAuthClientProvider(
            server_url=VISIER_MCP_SERVER_URL,
            client_metadata=OAUTH_CLIENT_STATIC_METADATA,
            storage=InMemoryTokenStorage(),
            redirect_handler=handle_redirect,
            callback_handler=automated_callback_handler
        )

        auth_server_url=VISIER_MCP_SERVER_URL.rstrip("/") + "/hr/oauth2"
        oauth_provider.context.protected_resource_metadata = ProtectedResourceMetadata(
            resource=AnyHttpUrl(VISIER_MCP_SERVER_URL),
            authorization_servers=[AnyHttpUrl(auth_server_url)]
        )

    client = MultiServerMCPClient({
        "visier-service": {
            "transport": "streamable_http",
            "url": VISIER_MCP_SERVER_URL,
            "auth": oauth_provider
        }
    })

    try:
        mcp_tools = await client.get_tools()
        available_tools.extend(mcp_tools)
        print(f"\n Authenticated! Tools: {[t.name for t in mcp_tools]}")

        app_agent = create_agent(
            get_llm_provider(), 
            mcp_tools,
            system_prompt=SYSTEM_PROMPT,
            debug=VERBOSE_LLM_LOGGING
        )

        ui_server.set_callbacks(set_captured_code, get_agent, get_server_url, get_model_name, get_tools)

        # Start the web UI after successful authentication
        ui_server.start_ui_in_background()
        await asyncio.sleep(0.1)  # Just a tiny delay to let the server start
        ui_server.open_ui()

        try:
            while True:
                await asyncio.sleep(5)  # Longer sleep since this is just keepalive
        except KeyboardInterrupt:
            print("\nShutting down...")
        
    except Exception:
        print("\nDetailed Error Traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())