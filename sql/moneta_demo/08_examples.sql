/* =============================================================================
   MonetaDemo - 08: example calls (run any line in SSMS: select it + F5)
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
-- contragents
EXEC ai_api.usp_GetContragents;                                        -- first 50 active
EXEC ai_api.usp_GetContragents @Search = N'Варна';                     -- search in code/name/EIK/VAT
EXEC ai_api.usp_GetContragents @ContragentType = 'S';                  -- suppliers
EXEC ai_api.usp_GetContragents @City = N'София', @PageSize = 10;
EXEC ai_api.usp_GetContragentByCode @Code = N'K0001';                  -- card + sales last 12 months

-- articles and stock
EXEC ai_api.usp_GetArticles @Search = N'кафе';
EXEC ai_api.usp_GetArticles @GroupCode = N'IT', @OnlyInStock = 1;
EXEC ai_api.usp_GetArticleStock @Code = N'IT-004';

-- documents
DECLARE @From DATE = DATEADD(MONTH, -1, CAST(GETDATE() AS DATE)), @To DATE = CAST(GETDATE() AS DATE);
EXEC ai_api.usp_GetDocuments @DateFrom = @From, @DateTo = @To, @DocTypeCode = 'INV';
EXEC ai_api.usp_GetDocument      @DocTypeCode = 'INV', @DocNumber = '0000000001';
EXEC ai_api.usp_GetDocumentLines @DocTypeCode = 'INV', @DocNumber = '0000000001';

-- reports
DECLARE @YearAgo DATE = DATEADD(DAY, -365, CAST(GETDATE() AS DATE)), @Today DATE = CAST(GETDATE() AS DATE);
EXEC ai_api.usp_SalesReport @DateFrom = @YearAgo, @DateTo = @Today, @GroupBy = 'month';
EXEC ai_api.usp_SalesReport @DateFrom = @YearAgo, @DateTo = @Today, @GroupBy = 'contragent', @Top = 5;
EXEC ai_api.usp_SalesReport @DateFrom = @YearAgo, @DateTo = @Today, @GroupBy = 'group';

-- lookups
EXEC ai_api.usp_GetLookups;

-- security check: run these while connected AS moneta_ai_reader (new SSMS connection, SQL login)
-- EXEC ai_api.usp_GetContragents;            -- works
-- SELECT TOP 1 * FROM dbo.Contragents;        -- fails: permission denied (by design)
GO
