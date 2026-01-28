import asyncio
import os
import traceback
import webbrowser
from threading import Thread

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, ProtectedResourceMetadata
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
from langchain_ollama import ChatOllama
from pydantic import AnyHttpUrl
from web.web_ui_server import WebUIServer
from .messages import SYSTEM_PROMPT

# Check for required environment variables
if (os.environ.get("VISIER_OAUTH_CLIENT_ID") is None or
    os.environ.get("VISIER_OAUTH_CLIENT_SECRET") is None or
    os.environ.get("VISIER_MCP_SERVER_URL") is None):
    raise ValueError("Please set VISIER_OAUTH_CLIENT_ID, VISIER_OAUTH_CLIENT_SECRET, and VISIER_MCP_SERVER_URL environment variables. See README for details.")

USE_BEDROCK = (os.environ.get("AWS_ACCESS_KEY_ID") is not None and
               os.environ.get("AWS_SECRET_ACCESS_KEY") is not None and
               os.environ.get("AWS_SESSION_TOKEN") is not None)

VISIER_OAUTH_CLIENT_ID = os.environ["VISIER_OAUTH_CLIENT_ID"]
VISIER_OAUTH_CLIENT_SECRET = os.environ["VISIER_OAUTH_CLIENT_SECRET"]
VISIER_MCP_SERVER_URL = os.environ["VISIER_MCP_SERVER_URL"]
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5")

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
    if USE_BEDROCK:
        return "AWS Bedrock (Claude Sonnet)"
    else:
        return f"Ollama ({OLLAMA_MODEL})"

def get_tools():
    """Callback function to get the available tools list"""
    return [tool.name for tool in available_tools]

# Set up the callbacks
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
        await asyncio.sleep(0.5)
    return captured_code, captured_state

async def handle_redirect(auth_url: str) -> None:
    print(f"\n Opening browser: {auth_url}")
    webbrowser.open(auth_url)

# --- MAIN ---
async def main():
    global app_agent
    
    print("Starting MCP client with OAuth authentication...")
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
        print("Connecting and exchanging token...")
        tools = await client.get_tools()
        available_tools.extend(tools)  # Store tools globally
        print(f"\n Authenticated! Tools: {[t.name for t in tools]}")
        
        # Create agent with appropriate LLM and system prompt
        if USE_BEDROCK:
            print("\n Creating AWS Bedrock agent...")
            base_model = ChatBedrockConverse(
                model_id="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
                region_name="us-west-2"
            )
        else:
            print(f"\n Creating Ollama agent with model={OLLAMA_MODEL}...")
            base_model = ChatOllama(model=OLLAMA_MODEL)

        app_agent = create_agent(base_model, tools, system_prompt=SYSTEM_PROMPT)

        # Start the web UI
        ui_server.start_ui_in_background()
        await asyncio.sleep(1)
        ui_server.open_ui()

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
        
    except Exception:
        print("\nDetailed Error Traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())