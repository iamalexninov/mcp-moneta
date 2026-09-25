/* ============================================================================
   Moneta AI Gateway - 03: post-schema hardening. Run as sysadmin / db_owner.

   sqlcmd -S <server> -d MonetaAI -U <admin> -C -i 03_hardening.sql
   ========================================================================== */
SET NOCOUNT ON;
GO
-- Belt and braces on top of the ledger table: the app may only INSERT/SELECT audit rows.
DENY UPDATE, DELETE ON OBJECT::ai_gateway.audit_log TO ai_gateway_app;
DENY UPDATE, DELETE ON OBJECT::ai_gateway.audit_log TO ai_gateway_migrator;
GO

-- Verify the ledger digest (should return no errors). Schedule this daily and
-- store digests in immutable storage (Azure Blob immutable / WORM) in production:
--   EXECUTE sp_generate_database_ledger_digest;
GO

/* Recommended server-level settings (run once by the DBA; review first):
   - Force encryption for all connections (SQL Server Configuration Manager ->
     Protocols -> Force Encryption = Yes) with a CA-issued certificate.
   - Transparent Data Encryption for data at rest:
       USE master; CREATE MASTER KEY ENCRYPTION BY PASSWORD = '<strong>';
       CREATE CERTIFICATE TDECert WITH SUBJECT = 'MonetaAI TDE';
       -- BACK UP the certificate and private key before continuing!
       USE MonetaAI; CREATE DATABASE ENCRYPTION KEY WITH ALGORITHM = AES_256
         ENCRYPTION BY SERVER CERTIFICATE TDECert;
       ALTER DATABASE MonetaAI SET ENCRYPTION ON;
   - SQL Server Audit for logins and permission changes on ai_gateway.
   - Disable the sa login; use Windows/Entra ID auth for administrators.
*/
PRINT 'Hardening applied.';
GO
