# 11. Connect your Moneta tables (Test_Ninov) to the gateway

The gateway reads four real Moneta tables **read-only** through a second database connection:
`N_Contragent`, `N_Item`, `D_SaleInvoiceHeader`, `D_SaleInvoiceLine` (lines link to the header via `master_id` → `Id`).
The gateway's own data (users, logins, audit) stays in `moneta_dev.db`, unchanged.

## 1. Check you have the ODBC driver (PowerShell)

```powershell
Get-OdbcDriver | Where-Object Name -like '*SQL Server*' | Select-Object Name
```
You need **ODBC Driver 18 for SQL Server** (17 also works; then write 17 below). If it's missing, install it from Microsoft ("Download ODBC Driver for SQL Server").

## 2. Add one line to `.env`

```ini
GATEWAY_ERP_ODBC='Driver={ODBC Driver 18 for SQL Server};Server=(localdb)\MSSQLLocalDB;Database=Test_Ninov;Trusted_Connection=yes;TrustServerCertificate=yes'
```
* Use **single quotes** around the value, so the `\` in `(localdb)\MSSQLLocalDB` is kept as-is.
* `Trusted_Connection=yes` means your Windows login, the same one SSMS uses. No password.
* `TrustServerCertificate=yes` is fine for LocalDB on your own PC. Never use it for a server on the network.

## 3. Test the connection

```powershell
python -m gateway.cli check-moneta
```
Expected: the server and database name, and for each of the 4 tables its row count, number of columns, and which columns the `search` parameter looks in. If it fails, the message shows the exact driver error.

## 4. Restart the gateway and MCP server

The new tools then appear in Claude.ai automatically. There's nothing to change in the connector, but start a new chat.

| Claude.ai tool | REST endpoint | What it returns | Permission |
|---|---|---|---|
| `moneta_contragents` | `GET /api/v1/moneta/contragents?search=&limit=&offset=` | Contragents, newest first | customers:read |
| — | `GET /api/v1/moneta/contragents/{id}` | One contragent | customers:read |
| `moneta_items` | `GET /api/v1/moneta/items?search=&limit=&offset=` | Items, newest first | products:read |
| — | `GET /api/v1/moneta/items/{id}` | One item | products:read |
| `moneta_invoices` | `GET /api/v1/moneta/invoices?date_from=&date_to=&contragent_id=&document_type=&search=&limit=&offset=` | Invoice headers, newest first | reports:read |
| `moneta_invoice` | `GET /api/v1/moneta/invoices/{id}` | Header + all its lines | reports:read |

Try in Claude.ai: *"Show the last 10 invoices from Moneta"*, *"Show invoice H0001 with its lines"*, *"Find contragents with 'ООД' in the name"*.

## How it stays safe

* Only `SELECT`s. Table names are fixed in code, column names come from the database's own metadata, and every value is a bound parameter (no SQL injection).
* Lists are paged: max 200 rows per call. Binary columns (images, row versions) are left out.
* Every call is written to the audit log (Admin → Audit log).
* **Personal data:** contragent rows may contain names, phones and e-mails. Use anonymized or demo data while Claude.ai Free is the client.

Once you've seen the data in Claude, the next step is to replace the generic reads with `ai_api` views and stored procedures written for these exact columns: proper names, document types, totals and reports.
