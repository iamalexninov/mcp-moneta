# 2. Running the whole build

## 2.1 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ (tested 3.11, image uses 3.12) | |
| Microsoft ODBC Driver 18 for SQL Server | 18.x | Only when connecting to SQL Server ([05](05-mssql-connection.md)) |
| Docker (optional) | 24+ | For the compose stack / local SQL Server |
| cloudflared or ngrok (optional) | latest | To expose localhost over HTTPS for Claude.ai |

## 2.2 Local development (SQLite)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

python -m gateway.cli init-db                               # create tables
python -m gateway.cli create-admin --tenant "Demo Company" \
       --email admin@demo.bg --name "Admin"                 # you'll be prompted for a password (min 12 chars)
python -m gateway.cli seed-demo --tenant "Demo Company"     # 15 products, 5 customers, 120 orders
python -m gateway.cli register-mcp-server                   # prints MCP_CLIENT_SECRET once -> put it in .env
```

Start both services (two terminals, with `.env` in the working directory):

```bash
uvicorn gateway.main:app --port 8000        # gateway: http://localhost:8000/admin  (OpenAPI: /docs in dev)
python -m mcp_server.server                 # MCP:     http://localhost:8001/mcp
```

Verify:

```bash
curl -i -X POST http://localhost:8001/mcp -d '{}' -H 'content-type: application/json'
# -> 401 + WWW-Authenticate: Bearer ... resource_metadata="http://localhost:8001/.well-known/oauth-protected-resource/mcp"

python scripts/e2e_demo.py --email admin@demo.bg --password '<password>'
# 1. discovered authorization server ... 5. tools: [...]  and a result from each tool
```

`scripts/e2e_demo.py` does exactly what Claude.ai does: discovery → DCR → consent with PKCE → token → MCP `initialize` → `tools/list` → `tools/call`.

## 2.3 Tests

```bash
pytest -q                                   # 35 tests on SQLite (~6 s)

# the same suite on SQL Server (use an EMPTY throwaway database):
TEST_DATABASE_URL="mssql+pyodbc://sa:<pw>@localhost:1433/MonetaAITest?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes" pytest -q
```

## 2.4 Exposing it to Claude.ai (HTTPS required)

Claude.ai connects from Anthropic's cloud, so `localhost` is not reachable. For a demo, use two free Cloudflare quick tunnels. The authorization server and the MCP server each get their own public HTTPS URL.

```bash
cloudflared tunnel --url http://localhost:8000     # prints https://<a>.trycloudflare.com  (gateway)
cloudflared tunnel --url http://localhost:8001     # prints https://<b>.trycloudflare.com  (MCP)
```

Put the URLs in `.env` and restart both services:

```ini
GATEWAY_PUBLIC_URL=https://<a>.trycloudflare.com
GATEWAY_MCP_RESOURCE_URL=https://<b>.trycloudflare.com/mcp
MCP_PUBLIC_URL=https://<b>.trycloudflare.com/mcp
MCP_ISSUER_URL=https://<a>.trycloudflare.com
MCP_GATEWAY_INTERNAL_URL=http://localhost:8000
```

Then follow [04 §4.3](04-mcp-server-and-claude.md#43-connect-claudeai-free-plan). ngrok works the same way (`ngrok http 8000`, `ngrok http 8001`).

> Quick-tunnel URLs change on each restart. Registered connections then break, and you must remove and re-add the connector in Claude. For a stable demo use a named Cloudflare tunnel or deploy (2.5).

## 2.5 Docker Compose (SQL Server + gateway + MCP + Caddy TLS)

```bash
cp .env.example .env
# set: MSSQL_SA_PASSWORD, PUBLIC_HOST=ai.example.bg (DNS -> this server),
#      GATEWAY_PUBLIC_URL=https://ai.example.bg, GATEWAY_MCP_RESOURCE_URL=https://ai.example.bg/mcp,
#      MCP_PUBLIC_URL=https://ai.example.bg/mcp, MCP_ISSUER_URL=https://ai.example.bg,
#      GATEWAY_SESSION_SECRET=<random>, GATEWAY_DATABASE_URL=... (see docs/05)
docker compose up -d mssql
# create DB, logins and schema (docs/05 §5.3), then:
docker compose run --rm gateway python -m gateway.cli create-admin --tenant "Client Ltd" --email admin@client.bg --name Admin
docker compose run --rm gateway python -m gateway.cli register-mcp-server   # put secret into .env
docker compose up -d --build
```

Caddy obtains a Let's Encrypt certificate automatically and routes `/mcp` and `/.well-known/oauth-protected-resource*` to the MCP server. Everything else goes to the gateway. With one origin, the authorization server and the MCP server share a hostname.

## 2.6 Production deployment (recommended shape)

```
Internet ──► WAF / Azure Front Door / Caddy (TLS 1.2+, rate limits, optional IP allow-list for /mcp)
              ├── /mcp, /.well-known/oauth-protected-resource*  ──► MCP server (2+ replicas, stateless tokens)
              └── /*                                             ──► Gateway (2+ replicas)
                                                                      │  private network / VNet
                                                                      ▼
                                                           SQL Server (Moneta) - TLS, TDE, ledger audit
Secrets: Key Vault (session secret, MCP secret, signing key, DB credentials or managed identity)
Logs: stdout JSON → SIEM (Sentinel/Splunk/ELK); alert on "denied" spikes, refresh reuse, code replay
```

* Set `GATEWAY_ENVIRONMENT=prod`. The app then refuses to start without HTTPS URLs, a real secret and SQL Server.
* Set `GATEWAY_AUTO_CREATE_TABLES=false`. Schema changes are applied by the DBA with `sql/mssql/*.sql`.
* Run uvicorn behind the proxy with `--proxy-headers --forwarded-allow-ips=<proxy IP>` so audit logs and rate limits see real client IPs. Never expose the gateway port directly when trusting forwarded headers.
* Put `keys/` on a persistent, private volume (or better, Key Vault), shared by all gateway replicas.
* For multiple replicas: move the rate limiter to Redis/WAF. Both services are otherwise stateless (sessions and grants live in SQL).

## 2.7 Operations cheat-sheet

| Task | Command |
|---|---|
| Create tenant admin | `python -m gateway.cli create-admin --tenant T --email E --name N` |
| Rotate token signing key | `python -m gateway.cli rotate-keys` (old public key stays valid for verification) |
| Rotate MCP client secret | `python -m gateway.cli register-mcp-server`, update `MCP_CLIENT_SECRET`, restart MCP |
| Verify audit chain | `python -m gateway.cli verify-audit` (exit code 2 if broken) |
| Verify SQL ledger | `EXECUTE sp_verify_database_ledger_from_digest_storage;` (after configuring digest storage) |
| Revoke a user's AI access | Admin panel → Connections → Revoke (or disable the user) |
