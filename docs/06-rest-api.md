# 6. REST API reference (`/api/v1`)

All endpoints require `Authorization: Bearer <API token>`. The token must have audience `<GATEWAY_PUBLIC_URL>/api`, and in normal operation it is obtained by the MCP server via token exchange. In dev, interactive OpenAPI docs are at `http://localhost:8000/docs`.

Common responses: `401` missing/invalid/revoked token · `403` missing scope · `404` not found · `409` conflict (stock) · `413` body > 1 MB · `422` validation (field paths, input never echoed) · `429` rate limited (`Retry-After`) · `500` `{"detail":"Internal error","request_id":"…"}`.

Every response carries `X-Request-ID`. Every mutating call and report is written to the audit log.

---

## GET `/api/v1/me`
Returns the caller identity: `user_id, tenant_id, role, client_id, scopes`.

## GET `/api/v1/reports/sales`  *(reports:read)*

| Query | Type | Rules |
|---|---|---|
| `date_from`, `date_to` | date | inclusive; `date_to ≥ date_from`; ≤ 366 days |
| `group_by` | `product` \| `customer` \| `category` \| `month` | default `product` |
| `top` | int | 1-100, default 20 |

```json
{
  "date_from": "2026-01-01", "date_to": "2026-06-30", "group_by": "category", "currency": "EUR",
  "rows": [{"key": "Coffee", "label": "Coffee", "orders": 75, "quantity": 612, "net": "10231.40", "gross": "12277.68"}],
  "total_net": "25100.10", "total_gross": "30120.12", "order_count": 120
}
```
Cancelled orders are excluded. Rows are sorted by net revenue (chronologically for `month`).

## GET `/api/v1/products`  *(products:read)*
`q` (≤ 100 chars, matches SKU or name; `%`/`_` are literal), `limit` 1-100. Returns `[{sku, name, category, unit_price, currency, vat_rate, stock_qty}]`.

## POST `/api/v1/products/import`  *(products:write)*

```json
{
  "items": [
    {"sku": "OFF-100", "name": "Paper A3 500", "category": "Office", "unit_price": "12.90",
     "currency": "EUR", "vat_rate": "20", "stock_qty": 40, "description": "80 g/m²"}
  ],
  "mode": "create_only",
  "dry_run": true
}
```
* `items`: 1-500 rows. `sku` matches `^[A-Za-z0-9][A-Za-z0-9._\-/]*$` (≤ 64). `unit_price` 0-10,000,000 with 2 decimals. `currency` ∈ EUR/BGN/USD. Unknown fields → 422. Duplicate SKUs → 422.
* `mode`: `create_only` (default) skips existing SKUs; `upsert` updates them.
* `dry_run`: **default `true`**, which returns what would happen without writing.

Response: `{"dry_run": true, "created": 1, "updated": 0, "skipped": 0, "rows": [{"sku": "OFF-100", "action": "create", "reason": null}]}`

## GET `/api/v1/customers`  *(customers:read)*
`q`, `limit`. Returns `[{code, name, city}]`.

## POST `/api/v1/orders`  *(orders:write)* → `201`

```json
{
  "customer_code": "C0001",
  "lines": [{"sku": "OFF-001", "quantity": 10}, {"sku": "OFF-002", "quantity": 2}],
  "notes": "Deliver Monday",
  "idempotency_key": "3f9a1c0e2b7d4a55"
}
```
* 1-50 lines, quantity 1-100,000. **No price fields accepted**: unit price and VAT come from the product record.
* Checks: customer exists in the tenant (404), SKUs exist and are active (404), stock sufficient (409), gross total ≤ `GATEWAY_MAX_ORDER_TOTAL` (422).
* `idempotency_key` (8-64 chars `[A-Za-z0-9_-]`): repeating it returns the original order with `"idempotent_replay": true`.
* The order is created with status **`draft`** and number `AI-YYYYMMDD-NNNNNN`.

```json
{
  "order_number": "AI-20260925-000121", "status": "draft",
  "customer_code": "C0001", "customer_name": "Sofia Tech OOD", "currency": "EUR",
  "total_net": "149.92", "total_vat": "29.98", "total_gross": "179.90",
  "lines": [{"sku": "OFF-001", "name": "Paper A4 500", "quantity": 2, "unit_price": "74.96", "vat_rate": "20.00", "line_net": "149.92"}],
  "idempotent_replay": false
}
```

---

## OAuth endpoints (for AI clients and the MCP server)

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/oauth-authorization-server` | RFC 8414 metadata |
| `GET /.well-known/jwks.json` | Public ES256 keys |
| `POST /oauth/register` | RFC 7591 DCR (JSON). Public clients; allow-listed redirect URIs only |
| `GET/POST /oauth/authorize` | Login + consent page; code + PKCE S256; `resource` = MCP URL |
| `POST /oauth/token` | form-encoded; `authorization_code`, `refresh_token`, `urn:ietf:params:oauth:grant-type:token-exchange` (MCP server only, HTTP Basic client auth) |
| `POST /oauth/revoke` | RFC 7009; revoking a refresh token revokes the whole connection |

### Calling the API manually (dev)
```bash
# 1. get an MCP-audience token via the e2e flow (or Claude), then exchange it as the MCP server:
curl -s -u moneta-mcp-server:$MCP_CLIENT_SECRET http://localhost:8000/oauth/token \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d subject_token_type=urn:ietf:params:oauth:token-type:access_token \
  -d subject_token=$USER_TOKEN
# 2. call the API
curl -s -H "Authorization: Bearer $API_TOKEN" "http://localhost:8000/api/v1/reports/sales?date_from=2026-01-01&date_to=2026-06-30&group_by=month"
```
