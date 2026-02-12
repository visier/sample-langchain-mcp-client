"""
OAuth2 Username/Password Authentication implementation for HTTPX.

Implements Resource Owner Password Credentials Grant (RFC 6749 Section 4.3)
for direct authentication using username and password.
"""

from collections.abc import AsyncGenerator
import logging
import time

import httpx
from urllib.parse import urljoin

from mcp.client.auth.oauth2 import TokenStorage, OAuthFlowError
from mcp.shared.auth import OAuthToken
from mcp.shared.auth_utils import calculate_token_expiry

logger = logging.getLogger(__name__)


class OAuthPasswordGrantClientProvider(httpx.Auth):
    """
    OAuth2 `password` grant authentication for httpx.
    Uses username and password for direct authentication without browser flow.
    """

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        username: str,
        password: str,
        client_id: str,
        client_secret: str,
        storage: TokenStorage,
        scope: str | None = None,
        timeout: float = 30.0,
        visier_tenant_vanity: str = None
    ):
        """Initialize OAuth2 password authentication.

        Args:
            server_url: The MCP server URL.
            username: Resource owner username.
            password: Resource owner password.
            client_id: OAuth client ID.
            client_secret: OAuth client secret.
            storage: Token storage implementation.
            scope: Optional scope for the access token.
            timeout: Timeout for token requests.
            visier_tenant_vanity: Optional Visier tenant vanity for constructing token endpoint URL.
        """
        self.server_url = server_url
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.storage = storage
        self.scope = scope
        self.timeout = timeout
        self._token: OAuthToken | None = None
        self._initialized = False
        self.visier_tenant_vanity = visier_tenant_vanity

    async def _get_token_endpoint(self) -> str:
        """Get the token endpoint URL."""
        if self.visier_tenant_vanity:
            return f"https://{self.visier_tenant_vanity}.localdev.local:8080/VServer/oauth2/token"

        if "/visier-query-mcp" in base_url:
            base_url = base_url.replace("/visier-query-mcp", "")
        return urljoin(base_url + "/", "hr/oauth2/token") # i.e. https://{vanity_name}.app.visier.com/hr/oauth2/token

    async def _exchange_password_for_token(self) -> OAuthToken:
        """Exchange username/password for access token using password grant."""
        token_endpoint = await self._get_token_endpoint()
        token_data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "resource": self.server_url # IMPORTANT: The `resource` param value must be the MCP server URL
        }

        logger.debug(f"Requesting token from {token_endpoint}")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                token_endpoint,
                data=token_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                }
            )
            
            if response.status_code != 200:
                error_details = response.text
                print("token_endpoint=", token_endpoint)
                logger.error(f"Token request failed: {response.status_code} - {error_details}")
                raise OAuthFlowError(f"Token request failed: {response.status_code} - {error_details}")
            
            token_data = response.json()
            logger.debug("Token request successful")

            expires_in = None
            if "expires_in" in token_data:
                expires_in = int(calculate_token_expiry(int(token_data["expires_in"])))
            
            return OAuthToken(
                access_token=token_data["access_token"],
                token_type=token_data.get("token_type", "Bearer"),
                expires_in=expires_in,
                refresh_token=token_data.get("refresh_token"),
                scope=token_data.get("scope")
            )

    async def _refresh_token_if_needed(self) -> OAuthToken:
        """Refresh token if it's expired or about to expire."""
        if not self._token:
            # Get new token
            self._token = await self._exchange_password_for_token()
            await self.storage.set_tokens(self._token)
            return self._token
        
        if self._token.expires_in and (time.time() + 60) >= self._token.expires_in:
            logger.debug("Token expired or about to expire, getting new token")
            self._token = await self._exchange_password_for_token()
            await self.storage.set_tokens(self._token)
        
        return self._token

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Add OAuth2 Bearer token to the request."""
        await self.tokens() # Ensure token is loaded/initialized
        token = await self._refresh_token_if_needed()
        request.headers["Authorization"] = f"{token.token_type} {token.access_token}"

        response = yield request

        if response.status_code == 401:
            logger.debug("Received 401, refreshing token and retrying")
            self._token = await self._exchange_password_for_token()
            await self.storage.set_tokens(self._token)
            
            request.headers["Authorization"] = f"{self._token.token_type} {self._token.access_token}"
            
            yield request

    async def tokens(self) -> OAuthToken | None:
        """Get current tokens."""
        if not self._initialized:
            stored_token = await self.storage.get_tokens()
            if stored_token:
                self._token = stored_token
            self._initialized = True
        return self._token