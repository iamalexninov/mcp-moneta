/* =============================================================================
   MonetaDemo - 99: DELETE the demo database and its login (to start over).
   ============================================================================= */
USE master;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
IF DB_ID(N'MonetaDemo') IS NOT NULL
BEGIN
    ALTER DATABASE MonetaDemo SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE MonetaDemo;
    PRINT 'Database MonetaDemo dropped.';
END
GO
IF SUSER_ID(N'moneta_ai_reader') IS NOT NULL
BEGIN
    DROP LOGIN moneta_ai_reader;
    PRINT 'Login moneta_ai_reader dropped.';
END
GO
