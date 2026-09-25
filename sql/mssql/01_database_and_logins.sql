/* ============================================================================
   Moneta AI Gateway - 01: database, schema and least-privilege logins
   Run as a sysadmin with sqlcmd (never commit real passwords):

   sqlcmd -S <server> -U <admin> -C -i 01_database_and_logins.sql ^
          -v DB_NAME="MonetaAI" MIGRATOR_PASSWORD="<long random>" APP_PASSWORD="<long random>"

   Two logins:
     ai_gateway_migrator  DDL in schema ai_gateway only. Used by deployments.
     ai_gateway_app       DML only. Used by the running gateway. Cannot change
                          schema, cannot UPDATE/DELETE the audit log.
   ========================================================================== */
SET NOCOUNT ON;
GO
IF DB_ID(N'$(DB_NAME)') IS NULL
    CREATE DATABASE [$(DB_NAME)];
GO
USE [$(DB_NAME)];
GO
IF SCHEMA_ID(N'ai_gateway') IS NULL
    EXEC(N'CREATE SCHEMA ai_gateway AUTHORIZATION dbo');
GO

/* ---- migration login ---- */
IF SUSER_ID(N'ai_gateway_migrator') IS NULL
    CREATE LOGIN ai_gateway_migrator WITH PASSWORD = N'$(MIGRATOR_PASSWORD)',
        CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = [$(DB_NAME)];
GO
IF USER_ID(N'ai_gateway_migrator') IS NULL
    CREATE USER ai_gateway_migrator FOR LOGIN ai_gateway_migrator WITH DEFAULT_SCHEMA = ai_gateway;
GO
GRANT CREATE TABLE, CREATE VIEW TO ai_gateway_migrator;
GRANT ENABLE LEDGER TO ai_gateway_migrator;  -- for the append-only audit ledger table
GRANT ALTER, REFERENCES, SELECT, INSERT, UPDATE, DELETE ON SCHEMA::ai_gateway TO ai_gateway_migrator;
GO

/* ---- runtime login ---- */
IF SUSER_ID(N'ai_gateway_app') IS NULL
    CREATE LOGIN ai_gateway_app WITH PASSWORD = N'$(APP_PASSWORD)',
        CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = [$(DB_NAME)];
GO
IF USER_ID(N'ai_gateway_app') IS NULL
    CREATE USER ai_gateway_app FOR LOGIN ai_gateway_app WITH DEFAULT_SCHEMA = ai_gateway;
GO
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::ai_gateway TO ai_gateway_app;
-- explicitly no DDL, no EXECUTE on arbitrary procedures, no access to other schemas
DENY ALTER ON SCHEMA::ai_gateway TO ai_gateway_app;
DENY VIEW DEFINITION ON SCHEMA::ai_gateway TO ai_gateway_app;
GO
PRINT 'Database, schema and logins ready.';
GO
