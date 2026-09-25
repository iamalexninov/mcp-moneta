/* ============================================================================
   Moneta AI Gateway - 04: EXAMPLE of reading the real Moneta database.

   The gateway never gets broad access to the Moneta ERP database. Instead the
   DBA publishes narrow, read-only VIEWS (and, for writes, STORED PROCEDURES
   with validation) in a dedicated schema, and grants only those to the
   ai_gateway_app user. The table and column names below are PLACEHOLDERS:
   replace them with the real Moneta objects after reviewing the Moneta schema
   with Innovasys.
   ========================================================================== */
-- USE [MonetaERP];   -- the real Moneta database
-- GO
-- CREATE SCHEMA ai_api AUTHORIZATION dbo;
-- GO
-- CREATE USER ai_gateway_app FOR LOGIN ai_gateway_app;   -- same login, no default rights here
-- GO
--
-- /* Read path: only the columns the AI needs, filtered to the company/tenant */
-- CREATE VIEW ai_api.v_products AS
--   SELECT a.ArticleCode AS sku, a.ArticleName AS name, g.GroupName AS category,
--          a.SalePrice AS unit_price, a.VatPercent AS vat_rate, s.Quantity AS stock_qty,
--          a.FirmId AS tenant_id
--   FROM dbo.Articles a
--   JOIN dbo.ArticleGroups g ON g.Id = a.GroupId
--   LEFT JOIN dbo.Stock s ON s.ArticleId = a.Id
--   WHERE a.IsActive = 1;
-- GO
-- GRANT SELECT ON ai_api.v_products TO ai_gateway_app;
--
-- /* Write path: a procedure that validates and creates a DRAFT order.
--    The app gets EXECUTE on this procedure only, never INSERT on Moneta tables. */
-- CREATE PROCEDURE ai_api.usp_create_draft_order
--   @tenant_id INT, @customer_code NVARCHAR(32), @lines_json NVARCHAR(MAX),
--   @idempotency_key VARCHAR(64), @created_by NVARCHAR(254)
-- AS
-- BEGIN
--   SET NOCOUNT, XACT_ABORT ON;
--   BEGIN TRAN;
--   -- 1. idempotency check, 2. validate customer & SKUs belong to @tenant_id,
--   -- 3. price from Moneta price lists, 4. insert draft document, 5. return it
--   COMMIT;
-- END
-- GO
-- GRANT EXECUTE ON ai_api.usp_create_draft_order TO ai_gateway_app;
--
-- Row-Level Security (defence in depth for multi-company databases):
-- CREATE FUNCTION ai_api.fn_tenant_filter(@tenant_id INT) RETURNS TABLE WITH SCHEMABINDING AS
--   RETURN SELECT 1 AS ok WHERE @tenant_id = CAST(SESSION_CONTEXT(N'tenant_id') AS INT);
-- CREATE SECURITY POLICY ai_api.tenant_policy
--   ADD FILTER PREDICATE ai_api.fn_tenant_filter(FirmId) ON dbo.Articles WITH (STATE = ON);
-- The gateway then runs EXEC sp_set_session_context 'tenant_id', @tid, @read_only = 1
-- at the start of every request (see docs/05-mssql-connection.md).
