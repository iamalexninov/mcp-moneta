/* =============================================================================
   MonetaDemo - 07: least-privilege access for the AI gateway

   Creates role ai_api_reader: may SELECT/EXECUTE objects in schema ai_api ONLY.
   It has no rights on dbo tables; the ai_api views/procedures still work through
   SQL Server ownership chaining (both schemas are owned by dbo).

   Option A (recommended): SQL login moneta_ai_reader
     1. Set @Password below (12+ chars, upper/lower/digit/symbol).
     2. Your instance must allow SQL logins: SSMS -> right-click the server ->
        Properties -> Security -> "SQL Server and Windows Authentication mode",
        then restart the SQL Server service.
   Option B: your Windows account (quick local dev) - see the end of this file.
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
IF DATABASE_PRINCIPAL_ID(N'ai_api_reader') IS NULL
    CREATE ROLE ai_api_reader AUTHORIZATION dbo;
GO
GRANT SELECT, EXECUTE ON SCHEMA::ai_api TO ai_api_reader;
DENY  SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER ON SCHEMA::dbo TO ai_api_reader;
DENY  VIEW DEFINITION ON SCHEMA::ai_api TO ai_api_reader;
GO

/* ---- Option A: SQL login (one batch: stops completely if the password is not set) ---- */
SET NOCOUNT ON;
DECLARE @Password NVARCHAR(128) = N'CHANGE_ME';        -- <<< set a strong password here

IF @Password = N'CHANGE_ME'
    THROW 50000, N'Edit 07_security.sql: set @Password before running it.', 1;

IF SUSER_ID(N'moneta_ai_reader') IS NULL
BEGIN
    DECLARE @Sql NVARCHAR(400) = N'CREATE LOGIN moneta_ai_reader WITH PASSWORD = '
        + QUOTENAME(@Password, '''') + N', CHECK_POLICY = ON, DEFAULT_DATABASE = MonetaDemo';
    EXEC (@Sql);
    PRINT 'Login moneta_ai_reader created.';
END
ELSE
    PRINT 'Login moneta_ai_reader already exists (password unchanged).';

IF DATABASE_PRINCIPAL_ID(N'moneta_ai_reader') IS NULL
    CREATE USER moneta_ai_reader FOR LOGIN moneta_ai_reader WITH DEFAULT_SCHEMA = ai_api;

IF IS_ROLEMEMBER(N'ai_api_reader', N'moneta_ai_reader') = 0
    ALTER ROLE ai_api_reader ADD MEMBER moneta_ai_reader;

PRINT 'moneta_ai_reader can use schema ai_api only.';
GO

/* ---- Option B: Windows account instead of a SQL login (uncomment, set your account) ----
CREATE USER [YOURDOMAIN\your.user] FOR LOGIN [YOURDOMAIN\your.user];
ALTER ROLE ai_api_reader ADD MEMBER [YOURDOMAIN\your.user];
   Note: if that Windows account is a sysadmin (typical on your own PC), the role
   does not restrict it - use Option A to really test least privilege.
*/
