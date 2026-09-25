# 5. Connecting Microsoft SQL Server

## 5.1 When to connect it

Connect SQL Server in phases, never straight to the live Moneta database:

| Phase | Database | Goal |
|---|---|---|
| **0. Now** | SQLite (default) | Run the whole stack, connect Claude.ai with demo data, learn the flow |
| **1. Your local SQL Server** | A **new, empty** database `MonetaAI` on your local instance | Prove connectivity, logins, TLS and the ledger audit table. The gateway uses its own demo ERP tables. |
| **2. Copy of Moneta** | A **restored backup / anonymised copy** of the client's Moneta DB, same server as `MonetaAI` or linked | Map the three methods to real Moneta tables through views and procedures (section 5.5) and validate results with Innovasys |
| **3. Production** | The client's Moneta server | Only after the [production checklist](08-production-checklist.md), with the DBA, a commercial Claude plan and a pentest |

**Rule:** the gateway always keeps its security tables (`users`, `oauth_*`, `audit_log`) in its **own** database/schema `ai_gateway`. It gets **read access to Moneta only through views** and **write access only through stored procedures**.

## 5.2 Install the driver

The gateway uses `pyodbc` + **Microsoft ODBC Driver 18 for SQL Server** (already in `requirements.txt` and the Dockerfile).

* **Windows**: install *ODBC Driver 18 for SQL Server* from Microsoft ("Download ODBC Driver for SQL Server"). Check with `odbcad32` → Drivers.
* **Ubuntu/Debian**:
  ```bash
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
  curl -fsSL https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
  sudo apt-get update && sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc
  odbcinst -q -d      # -> [ODBC Driver 18 for SQL Server]
  ```
* **macOS**: `brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release && brew install msodbcsql18`

## 5.3 Create the database, logins and schema (phase 1)

Run the scripts in `sql/mssql/` with `sqlcmd` (or paste them into SSMS with **SQLCMD Mode** enabled). Passwords are passed as variables and never stored in files. Generate strong ones, e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`.

```bash
# 1) as a sysadmin: database, schema ai_gateway, two least-privilege logins
sqlcmd -S localhost -U sa -C -i sql/mssql/01_database_and_logins.sql \
       -v DB_NAME="MonetaAI" MIGRATOR_PASSWORD="<random-1>" APP_PASSWORD="<random-2>"

# 2) as the migrator: tables (audit_log becomes an append-only LEDGER table)
sqlcmd -S localhost -d MonetaAI -U ai_gateway_migrator -P "<random-1>" -C -i sql/mssql/02_schema.sql

# 3) as a sysadmin: DENY UPDATE/DELETE on audit, TDE/encryption guidance
sqlcmd -S localhost -d MonetaAI -U sa -C -i sql/mssql/03_hardening.sql
```

Windows auth instead of `-U/-P`: use `-E`. `-C` trusts the server certificate. **Use it only on your local dev instance**, never against a production server.

| Login | Rights | Used by |
|---|---|---|
| `ai_gateway_migrator` | CREATE TABLE/VIEW, ALTER on schema `ai_gateway`, ENABLE LEDGER | Deployments only |
| `ai_gateway_app` | SELECT/INSERT/UPDATE/DELETE on schema `ai_gateway`; **DENY** ALTER, VIEW DEFINITION; **DENY** UPDATE/DELETE on `audit_log` | The running gateway |

## 5.4 Point the gateway at SQL Server

In `.env` (**quote the URL**, it contains `&`):

```ini
GATEWAY_DATABASE_URL="mssql+pyodbc://ai_gateway_app:<random-2>@localhost:1433/MonetaAI?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes"
GATEWAY_DB_SCHEMA=ai_gateway
GATEWAY_AUTO_CREATE_TABLES=false
```

* If the password contains special characters (`@ : / ? # &`), URL-encode it (`python -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" '<pw>'`).
* Named instance: `@HOSTNAME\\SQLEXPRESS` → use `@HOSTNAME:<port>` or `...?driver=...&instance=SQLEXPRESS`. Or enable TCP/IP and a fixed port in SQL Server Configuration Manager (recommended).
* **Windows Integrated auth** (gateway on a domain-joined Windows host): `mssql+pyodbc://@SQLHOST/MonetaAI?driver=ODBC+Driver+18+for+SQL+Server&Trusted_Connection=yes&Encrypt=yes`. Run the service as a dedicated gMSA with the same grants as `ai_gateway_app`.
* **Azure SQL / Managed Instance**: prefer Entra ID managed identity: `...?driver=ODBC+Driver+18+for+SQL+Server&Authentication=ActiveDirectoryMsi&Encrypt=yes`. No password at all.
* **Production:** remove `TrustServerCertificate=yes`. Install a CA-issued certificate on SQL Server and turn on *Force Encryption*.

Then bootstrap and start:

```bash
python -m gateway.cli create-admin --tenant "Demo Company" --email admin@demo.bg --name "Admin"
python -m gateway.cli seed-demo --tenant "Demo Company"      # optional demo data
python -m gateway.cli register-mcp-server                    # put MCP_CLIENT_SECRET in .env
uvicorn gateway.main:app --port 8000
python -m mcp_server.server
python scripts/e2e_demo.py --email admin@demo.bg --password '<pw>'
```

**Verified during development** against SQL Server 2022 (container `mcr.microsoft.com/mssql/server:2022-latest`) with the `ai_gateway_app` login: all scripts, the full e2e flow, the 35-test suite, and the ledger protection:

```
UPDATE ai_gateway.audit_log ...   -- as ai_gateway_app, and even as sa
Msg 37359: Updates are not allowed for the append only Ledger table 'ai_gateway.audit_log'.
```

Quick local SQL Server with Docker, if you don't have one:

```bash
docker run -d --name mssql -e ACCEPT_EULA=Y -e "MSSQL_SA_PASSWORD=<Strong!Passw0rd>" -p 1433:1433 mcr.microsoft.com/mssql/server:2022-latest
```

## 5.5 Mapping to the real Moneta schema (phase 2)

Everything that touches ERP data lives in **one file: `gateway/services/erp.py`**. The API contracts, MCP tools and all security layers stay the same. Recommended approach, together with Innovasys:

1. **Inventory**: identify Moneta's tables for articles/products, price lists, VAT groups, stock, partners/customers, sales documents and lines, and the company/firm key (the tenant).
2. **Read views** in a dedicated schema in the Moneta DB (e.g. `ai_api`). Expose only the columns the tools need and filter out inactive/internal rows. `sql/mssql/04_moneta_integration_example.sql` has templates (`ai_api.v_products`, …); the names there are placeholders.
3. **Write procedures** for imports and orders (`ai_api.usp_import_products`, `ai_api.usp_create_draft_order`). They validate, price from Moneta price lists, write **draft** documents with Moneta's own numbering, and enforce idempotency. The app login gets `EXECUTE` on those procedures only, and never INSERT/UPDATE on Moneta tables. This keeps Moneta's business rules in one place and avoids bypassing ERP logic.
4. **Grant**: `GRANT SELECT ON ai_api.v_products TO ai_gateway_app; GRANT EXECUTE ON ai_api.usp_create_draft_order TO ai_gateway_app;`. Grant nothing at schema `dbo` level.
5. **Re-implement** `sales_report`, `search_products`, `search_customers`, `import_products` and `create_order` in `erp.py` using `text()` queries against the views and procedures (still parameterised), for example:
   ```python
   from sqlalchemy import text
   rows = db.execute(text("SELECT sku, name, category, unit_price, 'EUR' AS currency, vat_rate, stock_qty "
                          "FROM ai_api.v_products WHERE tenant_id = :tid AND (sku LIKE :q ESCAPE '\\' OR name LIKE :q ESCAPE '\\') "
                          "ORDER BY sku OFFSET 0 ROWS FETCH NEXT :lim ROWS ONLY"),
                     {"tid": tenant_id, "q": _like(q or ""), "lim": limit})
   ```
6. **Tenant mapping**: map each gateway tenant to Moneta's company/firm id (add a column `moneta_firm_id` to `tenants`, or keep one gateway deployment per Moneta database).
7. **Validate** report totals against Moneta's own reports for a known period before going live.

If the gateway tables and Moneta are in different databases on the same server, use three-part names in the views (`MonetaERP.dbo.Articles`), or keep the views inside the Moneta DB and give the gateway a second connection. Cross-database ownership chaining should stay **off**.

## 5.6 Row-Level Security (defence in depth)

For a Moneta database that holds several companies, add SQL Server RLS so that even a bug in the gateway can't cross companies:

```sql
CREATE FUNCTION ai_api.fn_tenant_filter(@firm_id INT) RETURNS TABLE WITH SCHEMABINDING AS
  RETURN SELECT 1 AS ok WHERE @firm_id = CAST(SESSION_CONTEXT(N'tenant_id') AS INT);
CREATE SECURITY POLICY ai_api.tenant_policy
  ADD FILTER PREDICATE ai_api.fn_tenant_filter(FirmId) ON dbo.Articles WITH (STATE = ON);
```

In the gateway, set the context at the start of each request (e.g. in `api/deps.py` after the principal is known):

```python
db.execute(text("EXEC sp_set_session_context @key=N'tenant_id', @value=:t, @read_only=1"), {"t": principal.tenant_id})
```

`@read_only=1` prevents later statements in the same session from changing it. **Important with pooling:** unlike ADO.NET, SQLAlchemy's pool does not call `sp_reset_connection` by itself. Add a reset hook in `gateway/db.py` (pattern from the SQLAlchemy MSSQL docs) so a pooled connection never carries the previous request's tenant:

```python
@event.listens_for(engine, "reset")
def _reset_mssql(dbapi_connection, connection_record, reset_state):
    if not reset_state.terminate_only:
        dbapi_connection.execute("{call sys.sp_reset_connection}")
    dbapi_connection.rollback()
```

## 5.7 Operational checklist for the DBA

- [ ] TLS: CA certificate installed, *Force Encryption = Yes*, `TrustServerCertificate` **not** used by the app
- [ ] TDE enabled on `MonetaAI` (and Moneta), certificate backed up offline
- [ ] `ai_gateway_app` has no rights outside `ai_gateway` + granted `ai_api` objects
- [ ] `sa` disabled; admins use Windows/Entra auth
- [ ] Backups encrypted; restore tested
- [ ] SQL Server Audit on logins and permission changes
- [ ] Ledger digests generated daily and stored in immutable storage
- [ ] Firewall: port 1433 reachable only from the gateway hosts
