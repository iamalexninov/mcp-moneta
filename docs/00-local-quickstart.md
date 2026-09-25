# 0. Local quick start: run and test everything on your PC

Commands are shown for **Windows (PowerShell)** and **macOS/Linux**. Run everything from the repository's root folder: both services read `.env` from the current directory.

## 0. Prerequisites (once)

| Needed | Windows | macOS / Linux |
|---|---|---|
| Python 3.11+ | python.org installer (tick "Add to PATH") | `brew install python@3.12` / `apt install python3 python3-venv` |
| Git | git-scm.com | usually preinstalled |
| *(later, for SQL Server)* ODBC Driver 18 | "Microsoft ODBC Driver 18 for SQL Server" installer | see [05 §5.2](05-mssql-connection.md#52-install-the-driver) |
| *(later, for Claude.ai)* cloudflared | `winget install --id Cloudflare.cloudflared` | `brew install cloudflared` |

Check: `python --version` should print 3.11 or newer.

## 1. Get the code and install

```powershell
git clone -b claude/moneta-erp-claude-integration-o2v0zy https://github.com/iamalexninov/mcp-moneta.git
cd mcp-moneta
python -m venv .venv
```

Activate the virtual environment. **Do this in every new terminal:**
- Windows: `.venv\Scripts\Activate.ps1`. If PowerShell blocks it, first run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- macOS/Linux: `source .venv/bin/activate`

```powershell
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

## 2. Create the database, an admin, demo data and the MCP secret

```powershell
python -m gateway.cli init-db
python -m gateway.cli create-admin --tenant "Demo Company" --email admin@demo.bg --name "Admin"
```
It asks for a password (at least 12 characters, e.g. `Str0ng-Demo-Passw0rd!`). Remember it.

```powershell
python -m gateway.cli seed-demo --tenant "Demo Company"
python -m gateway.cli register-mcp-server
```
The last command prints two lines. Open `.env` in a text editor and paste the secret into the empty line:
```ini
MCP_CLIENT_SECRET=<the value it printed>
```
It is shown **only once**. If you lose it, run `register-mcp-server` again and update `.env`.

## 3. Start the two services (two terminals)

**Terminal 1: gateway** (REST API, sign-in server, admin panel)
```powershell
.venv\Scripts\Activate.ps1      # or: source .venv/bin/activate
uvicorn gateway.main:app --port 8000
```

**Terminal 2: MCP server**
```powershell
.venv\Scripts\Activate.ps1
python -m mcp_server.server
```
Both should print `Uvicorn running on http://127.0.0.1:800x`.

## 4. Test it (terminal 3)

### A. Admin panel in the browser
Open http://localhost:8000/admin and log in with `admin@demo.bg` and your password. Click through Dashboard, AI Agents, Users, Connections and Audit log. The Audit log should show the green "Hash chain verified" banner.

### B. API documentation
Open http://localhost:8000/docs to see the interactive REST API docs. They're only shown in dev mode.

### C. MCP server asks for sign-in
```powershell
curl.exe -i -X POST http://localhost:8001/mcp -H "content-type: application/json" -d "{}"
```
(macOS/Linux: plain `curl`.) Expected: `401 Unauthorized` and a `www-authenticate: Bearer ... resource_metadata="..."` header.

### D. Full end-to-end run (behaves exactly like Claude.ai)
```powershell
.venv\Scripts\Activate.ps1
python scripts/e2e_demo.py --email admin@demo.bg --password "Str0ng-Demo-Passw0rd!"
```
Expected output:
```
1. discovered authorization server: http://localhost:8000
2. registered client: dcr_...
3. user approved scopes: [...]
4. got access token (expires in 900 s) ...
5. tools: ['sales_report', 'search_products', 'search_customers', 'import_products', 'create_order']
   sales_report -> error=False: ...
   search_customers -> error=False: ...
   import_products -> error=False: { "dry_run": true, ...
   create_order -> error=False: { "order_number": "AI-...", "status": "draft", ...
```
Now refresh the admin panel. **Connections** shows the new connection and the **Audit log** shows every step. On **Connections**, click **Revoke**: the next tool call on that connection fails with "connection is no longer authorized". That's instant revocation.

### E. Automated test suite
The tests use their own temporary database, so the running services aren't affected.
```powershell
pytest -q
```
Expected: `35 passed`.

## 5. Test with real Claude.ai (Free plan)

Claude.ai runs in Anthropic's cloud, so it needs public HTTPS URLs for your PC.

1. Open **two more terminals** and start one tunnel in each:
   ```powershell
   cloudflared tunnel --url http://localhost:8000     # copy the https://AAAA.trycloudflare.com URL
   cloudflared tunnel --url http://localhost:8001     # copy the https://BBBB.trycloudflare.com URL
   ```
2. Edit `.env` (AAAA = gateway tunnel, BBBB = MCP tunnel):
   ```ini
   GATEWAY_PUBLIC_URL=https://AAAA.trycloudflare.com
   GATEWAY_MCP_RESOURCE_URL=https://BBBB.trycloudflare.com/mcp
   MCP_PUBLIC_URL=https://BBBB.trycloudflare.com/mcp
   MCP_ISSUER_URL=https://AAAA.trycloudflare.com
   MCP_GATEWAY_INTERNAL_URL=http://localhost:8000
   ```
3. Restart **both** services (Ctrl+C, then start them again as in step 3).
4. In Claude.ai:
   - **Settings → Privacy**: turn off model training.
   - **Customize → Connectors → Add custom connector**. Name `Moneta`, URL `https://BBBB.trycloudflare.com/mcp`, then **Add**, then **Connect**.
   - Sign in on the Moneta page that opens and approve. Tick the write permissions if you want to test imports and orders.
   - In a new chat: **+ → Connectors → enable Moneta**.
5. Try:
   - "Show me sales by category for the last 6 months."
   - "Which 5 customers bought the most this year?"
   - "Create an order for Sofia Tech: 10 × Paper A4 500 and 2 staplers."
   - Attach a price list (PDF or Excel), then: "Import these products into Moneta." Claude shows a preview first and asks before writing.

Quick-tunnel URLs change every time cloudflared restarts. When that happens, update `.env`, restart both services, then remove and re-add the connector in Claude.

*Optional, if you have Claude Code:* you can test without tunnels using `claude mcp add --transport http moneta http://localhost:8001/mcp`, then `/mcp` to sign in. This path hasn't been tried against a live Claude Code yet.

## 6. Switch to your SQL Server (when you're ready)

1. Install ODBC Driver 18.
2. Run the three scripts in `sql/mssql/` (exact commands in [05 §5.3](05-mssql-connection.md#53-create-the-database-logins-and-schema-phase-1)). They create an empty `MonetaAI` database; don't point this at the real Moneta database yet.
3. In `.env`, keep the quotes around the URL:
   ```ini
   GATEWAY_DATABASE_URL="mssql+pyodbc://ai_gateway_app:<APP_PASSWORD>@localhost:1433/MonetaAI?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"
   GATEWAY_DB_SCHEMA=ai_gateway
   GATEWAY_AUTO_CREATE_TABLES=false
   ```
4. Repeat step 2 from `create-admin` onwards (skip `init-db`), put the new MCP secret in `.env`, restart both services, and rerun test D.

## Common problems

| Symptom | Fix |
|---|---|
| `MCP_CLIENT_SECRET is not set` | Step 2: paste the secret into `.env`, and start from the repo folder |
| E2E step 5 fails with "no longer authorized" | Wrong secret in `.env`; run `register-mcp-server` again and restart the MCP server |
| "Account temporarily locked" | 5 wrong passwords; wait 15 minutes, or have an admin click **Unlock** on the Users page |
| `Address already in use` | Something else is on port 8000/8001; close it or change `--port` and the matching `.env` URLs |
| Claude.ai "Couldn't reach the MCP server" | A tunnel is down, or the URL in Claude isn't exactly `MCP_PUBLIC_URL` (including `/mcp`) |
