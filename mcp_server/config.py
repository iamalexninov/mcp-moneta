from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8001
    # Public URL of this MCP endpoint, exactly as users paste it into Claude.
    # Must equal GATEWAY_MCP_RESOURCE_URL (it is the token audience).
    public_url: str = "http://localhost:8001/mcp"
    # Issuer (public URL of the gateway / authorization server).
    issuer_url: str = "http://localhost:8000"
    # Where this server reaches the gateway REST API (private network in prod).
    gateway_internal_url: str = "http://localhost:8000"
    # Confidential client credentials for RFC 8693 token exchange.
    client_id: str = "moneta-mcp-server"
    client_secret: str = ""
    # Extra Host header values accepted (DNS-rebinding protection), e.g. "mcp.example.com".
    allowed_hosts: list[str] = []
    http_timeout: float = 15.0

    @property
    def api_audience(self) -> str:
        return f"{self.issuer_url.rstrip('/')}/api"


@lru_cache
def get_settings() -> McpSettings:
    return McpSettings()
