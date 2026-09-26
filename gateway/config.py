"""Central configuration. Every value can be overridden with an environment
variable prefixed ``GATEWAY_`` (or in a ``.env`` file)."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    # "dev" relaxes a few transport rules (plain HTTP cookies on localhost).
    # "staging" = internet-facing prototype: full hardening, but SQLite allowed.
    # Anything else is treated as production and hardening is enforced.
    environment: str = "dev"

    # Public URL of this service (issuer of every token). Must be HTTPS in production.
    public_url: str = "http://localhost:8000"

    # Public URL of the MCP server's endpoint. It is the OAuth "resource" /
    # token audience for tokens handed to AI clients.
    mcp_resource_url: str = "http://localhost:8001/mcp"

    # SQLAlchemy URL. Examples:
    #   sqlite:///./moneta_dev.db
    #   mssql+pyodbc://ai_gateway_app:***@sql01:1433/MonetaAI?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes
    database_url: str = "sqlite:///./moneta_dev.db"
    # Optional SQL Server schema for all gateway tables (e.g. "ai_gateway").
    db_schema: str | None = None
    # Create missing tables at startup. Handy for SQLite/dev; in production the
    # runtime login has no DDL rights and tables come from sql/mssql/*.sql.
    auto_create_tables: bool = True

    # Directory holding the ES256 signing keys (created on first start).
    keys_dir: str = "./keys"

    # Secret used to sign admin session cookies and CSRF tokens (>= 32 chars).
    session_secret: str = Field(default="dev-only-change-me-dev-only-change-me-0000", min_length=32)

    # Token lifetimes (seconds). Short access tokens + rotating refresh tokens.
    access_token_ttl: int = 900  # tokens held by AI clients (audience = MCP server)
    api_token_ttl: int = 300  # tokens minted for the MCP server to call the REST API
    refresh_token_ttl: int = 60 * 60 * 24 * 14
    auth_code_ttl: int = 60
    admin_session_ttl: int = 60 * 30

    # Brute-force protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Redirect URIs a dynamically registered OAuth client may use. DCR is open
    # by spec, so we restrict *where* codes can be delivered instead.
    allowed_redirect_uris: list[str] = [
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "http://localhost/callback",
        "http://127.0.0.1/callback",
        "cursor://anysphere.cursor-mcp/oauth/callback",
    ]

    # Business guard rails applied server side, whatever the AI asks for.
    max_import_rows: int = 500
    max_order_lines: int = 50
    max_order_total: float = 50_000.0

    @field_validator("public_url", "mcp_resource_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"

    @property
    def api_audience(self) -> str:
        return f"{self.public_url}/api"

    def check_production_safety(self) -> None:
        """Refuse to start with insecure settings outside dev."""
        if self.is_dev:
            return
        problems = []
        if not self.public_url.startswith("https://"):
            problems.append("GATEWAY_PUBLIC_URL must be https://")
        if not self.mcp_resource_url.startswith("https://"):
            problems.append("GATEWAY_MCP_RESOURCE_URL must be https://")
        if self.session_secret.startswith("dev-only"):
            problems.append("GATEWAY_SESSION_SECRET must be set to a random value")
        if self.database_url.startswith("sqlite") and self.environment != "staging":
            problems.append("SQLite is for development/staging only; use SQL Server")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
