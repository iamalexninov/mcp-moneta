# 8. Production checklist & roadmap

## 8.1 Before real client data (must-do)

**Legal / vendor**
- [ ] Client uses **Claude Team or Enterprise** (Commercial Terms: no training, DPA, SSO, admin controls), not Free/Pro. Until then, each user disables model training in Privacy settings and only demo data is used.
- [ ] DPA with Anthropic signed. Record of processing updated (GDPR Art. 30). DPIA if personal data volume warrants it.
- [ ] Innovasys agreement on the Moneta views/procedures (section 5.5) and on support responsibility.

**Configuration**
- [ ] `GATEWAY_ENVIRONMENT=prod` (enforces HTTPS URLs, real secret, SQL Server)
- [ ] `GATEWAY_SESSION_SECRET` random ≥ 48 chars, from a secret manager
- [ ] `GATEWAY_AUTO_CREATE_TABLES=false`; schema via `sql/mssql/*.sql`
- [ ] SQL connection with `Encrypt=yes` and **without** `TrustServerCertificate`
- [ ] Signing keys on a private persistent volume or Key Vault; rotation scheduled
- [ ] `MCP_CLIENT_SECRET` from a secret manager
- [ ] `GATEWAY_ALLOWED_REDIRECT_URIS` reduced to the assistants actually used
- [ ] Business limits reviewed: `GATEWAY_MAX_ORDER_TOTAL`, `GATEWAY_MAX_IMPORT_ROWS`

**Infrastructure**
- [ ] TLS 1.2+ with automatic renewal; HSTS; WAF with rate limits
- [ ] SQL Server not reachable from the internet; gateway ports not exposed directly
- [ ] uvicorn `--forwarded-allow-ips` set to the proxy IP only
- [ ] Optional: `/mcp` restricted to Anthropic egress `160.79.104.0/21` (+ other vendors' ranges if used)
- [ ] Logs shipped to a SIEM; alerts on `denied` spikes, `oauth.refresh_reuse`, `oauth.code_replay`, `oauth.pkce_fail`, 5xx
- [ ] Backups (DB + keys) encrypted and restore-tested

**Identity**
- [ ] MFA enrolled for every admin (enforced) and strongly recommended for all users
- [ ] Decide: keep built-in login or federate to Entra ID / Keycloak (03 §4.6)
- [ ] Quarterly access review using Admin → Connections / Users

**Assurance**
- [ ] `pytest` green on SQL Server
- [ ] Dependency audit (`pip-audit`) and container scan (Trivy) clean
- [ ] External penetration test (OAuth flows, tenant isolation, prompt-injection scenarios)
- [ ] Pilot with read-only roles first, then enable write scopes for a small group

## 8.2 Roadmap

| Priority | Item |
|---|---|
| High | Map the tools to the real Moneta schema (views + procedures), tenant ↔ Moneta firm mapping |
| High | SSO: delegate login to Entra ID (OIDC) with Conditional Access; passkeys/WebAuthn |
| High | CIMD support (Claude's recommended registration method; fewer registered clients) |
| Medium | Campaigns tool (`create_campaign_draft`), invoices lookup, stock alerts, customer statements |
| Medium | Redis-backed rate limiting and JWKS/token caches for multi-replica deployments |
| Medium | Admin UI: per-tenant tool enable/disable, per-user limits, CSV export of audit, anomaly alerts |
| Medium | Alembic migrations (instead of generated SQL) |
| Low | Document ingestion endpoint (upload PDF/Excel server-side, parse, then import) for assistants without file support |
| Low | MCP resources (e.g. `moneta://reports/templates`) and elicitation for confirmations inside the protocol |
