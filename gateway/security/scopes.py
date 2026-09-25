"""OAuth scopes and role -> scope mapping (RBAC).

A token's effective permissions are always the intersection of:
  1. what the AI client asked for,
  2. what the user ticked on the consent screen,
  3. what the user's role allows (re-checked on every API call).
"""

MCP_BASE = "mcp"

SCOPES: dict[str, str] = {
    MCP_BASE: "Connect an AI assistant to Moneta through the MCP gateway",
    "reports:read": "Read sales reports and aggregates",
    "products:read": "Search and read products",
    "products:write": "Create and update products (bulk import)",
    "customers:read": "Search and read customers",
    "orders:write": "Create sales orders",
}

ROLES: dict[str, set[str]] = {
    "admin": set(SCOPES),
    "manager": set(SCOPES),
    "sales": {MCP_BASE, "reports:read", "products:read", "customers:read", "orders:write"},
    "viewer": {MCP_BASE, "reports:read", "products:read", "customers:read"},
}

# Only these roles may sign into the administrator panel.
ADMIN_PANEL_ROLES = {"admin"}


def parse(scope_str: str | None) -> set[str]:
    return {s for s in (scope_str or "").split() if s}


def allowed_for_role(role: str) -> set[str]:
    return ROLES.get(role, set())


def resolve_requested(requested: set[str], role: str) -> set[str]:
    """Scopes an AI client may receive for this user.

    Clients (e.g. Claude) typically request only the base "mcp" scope that the
    MCP server advertises; that expands to everything the role permits and the
    user can then untick items on the consent screen.
    """
    role_scopes = allowed_for_role(role)
    if not requested or requested <= {MCP_BASE, "offline_access"}:
        return set(role_scopes)
    return (requested & role_scopes) | {MCP_BASE}
