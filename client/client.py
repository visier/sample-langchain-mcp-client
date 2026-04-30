import asyncio
import os
import traceback
import webbrowser
import logging
from threading import Thread

import httpx
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthToken, OAuthClientInformationFull, ProtectedResourceMetadata
from pydantic import AnyHttpUrl

from client.llm_provider import LLM_PROVIDER, LLM_MODEL_ID, get_current_model_name
from client.mcp_client_backend import create_mcp_client_backend
from web.web_ui_server import WebUIServer
from .oauth2 import OAuthPasswordGrantClientProvider

# Check for required environment variables
if (os.environ.get("VISIER_OAUTH_CLIENT_ID") is None or
    os.environ.get("VISIER_OAUTH_CLIENT_SECRET") is None or
    os.environ.get("VISIER_MCP_SERVER_URL") is None):
    raise ValueError("Please set VISIER_OAUTH_CLIENT_ID, VISIER_OAUTH_CLIENT_SECRET, and VISIER_MCP_SERVER_URL environment variables. See README for details.")

VISIER_OAUTH_CLIENT_ID = os.environ["VISIER_OAUTH_CLIENT_ID"]
VISIER_OAUTH_CLIENT_SECRET = os.environ["VISIER_OAUTH_CLIENT_SECRET"]
VISIER_MCP_SERVER_URL = os.environ["VISIER_MCP_SERVER_URL"]
VISIER_USERNAME = os.environ.get("VISIER_USERNAME")
VISIER_PASSWORD = os.environ.get("VISIER_PASSWORD")
VISIER_TENANT_VANITY = os.environ.get("VISIER_TENANT_VANITY")

USE_PASSWORD_GRANT = (VISIER_USERNAME is not None and VISIER_PASSWORD is not None)

AGENT_BACKEND = os.environ.get("AGENT_BACKEND", "langchain").lower()
LANGCHAIN_VERBOSE = os.environ.get("LANGCHAIN_VERBOSE", "false").lower() == "true"

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
available_prompts = []
ui_server = WebUIServer()

def set_captured_code(code, state):
    global captured_code, captured_state
    captured_code = code
    captured_state = state

def get_agent():
    return app_agent

def get_server_url():
    return VISIER_MCP_SERVER_URL

def get_model_name():
    if AGENT_BACKEND == "boto3":
        return f"Bedrock ({LLM_MODEL_ID})"
    return f"{LLM_PROVIDER} ({get_current_model_name()})"

def get_tools():
    return available_tools

def get_prompts():
    return available_prompts


ui_server.set_callbacks(set_captured_code, get_agent, get_server_url, get_model_name, get_tools, get_prompts)

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
        await asyncio.sleep(0.1)
    return captured_code, captured_state

async def handle_redirect(auth_url: str) -> None:
    print(f"\n Opening browser: {auth_url}")
    webbrowser.open(auth_url)


def _create_oauth_provider() -> httpx.Auth:
    """Create the appropriate OAuth provider based on environment config."""
    if USE_PASSWORD_GRANT:
        print("Starting MCP client with OAuth Password Grant authentication...")
        return OAuthPasswordGrantClientProvider(
            server_url=VISIER_MCP_SERVER_URL,
            username=VISIER_USERNAME,
            password=VISIER_PASSWORD,
            client_id=OAUTH_CLIENT_STATIC_METADATA.client_id,
            client_secret=OAUTH_CLIENT_STATIC_METADATA.client_secret,
            storage=InMemoryTokenStorage(),
            visier_tenant_vanity=VISIER_TENANT_VANITY
        )

    print("Starting MCP client with OAuth Authorization Code Grant authentication...")
    provider = OAuthClientProvider(
        server_url=VISIER_MCP_SERVER_URL,
        client_metadata=OAUTH_CLIENT_STATIC_METADATA,
        storage=InMemoryTokenStorage(),
        redirect_handler=handle_redirect,
        callback_handler=automated_callback_handler
    )
    auth_server_url = VISIER_MCP_SERVER_URL.rstrip("/") + "/hr/oauth2"
    provider.context.protected_resource_metadata = ProtectedResourceMetadata(
        resource=AnyHttpUrl(VISIER_MCP_SERVER_URL),
        authorization_servers=[AnyHttpUrl(auth_server_url)]
    )
    return provider


# --- MAIN ---
async def main():
    global app_agent

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    oauth_provider = _create_oauth_provider()
    backend = create_mcp_client_backend(VISIER_MCP_SERVER_URL, oauth_provider, AGENT_BACKEND)

    try:
        async with backend:
            available_tools.extend(backend.tool_definitions())
            available_prompts.extend(backend.prompt_definitions())

            print(f"\n Authenticated. Available MCP Tools: {[t['name'] for t in available_tools]}")
            print(f"\n Available MCP Prompts: {[p['name'] for p in available_prompts]}")

            app_agent = backend.create_agent(verbose=LANGCHAIN_VERBOSE)

            ui_server.set_callbacks(
                set_captured_code, get_agent, get_server_url, get_model_name, get_tools, get_prompts,
                get_prompt_messages_async=backend.get_prompt_messages
            )

            ui_server.start_ui_in_background()
            await asyncio.sleep(0.1)
            ui_server.open_ui()

            while True:
                await asyncio.sleep(5) # Longer sleep since this is just keepalive
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception:
        print("\nDetailed Error Traceback:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
