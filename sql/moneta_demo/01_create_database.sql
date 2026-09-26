/* =============================================================================
   MonetaDemo - 01: database + schemas
   A small Moneta-like ERP database for developing the AI gateway locally.

   Run in SSMS (connected to your local instance, e.g. localhost or .\SQLEXPRESS)
   or from a terminal:  sqlcmd -S localhost -E -C -i 01_create_database.sql
   Scripts are re-runnable: 01..06 create objects if missing / replace them.
   To start over completely run 99_drop_database.sql first.

   Schemas:
     dbo     ERP tables (like Moneta). Private: the AI gateway gets NO rights here.
     ai_api  Views, functions and stored procedures the gateway may use.
   ============================================================================= */
USE master;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
IF DB_ID(N'MonetaDemo') IS NULL
BEGIN
    -- Cyrillic_General_CI_AS: Bulgarian sorting/comparison, case-insensitive
    CREATE DATABASE MonetaDemo COLLATE Cyrillic_General_CI_AS;
    PRINT 'Database MonetaDemo created.';
END
ELSE
    PRINT 'Database MonetaDemo already exists.';
GO
ALTER DATABASE MonetaDemo SET RECOVERY SIMPLE;   -- dev database: no log backups needed
GO
USE MonetaDemo;
GO
IF SCHEMA_ID(N'ai_api') IS NULL
    EXEC(N'CREATE SCHEMA ai_api AUTHORIZATION dbo');
GO
PRINT 'Schemas ready: dbo (ERP tables), ai_api (gateway access layer).';
GO
