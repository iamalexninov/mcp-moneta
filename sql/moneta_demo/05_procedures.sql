/* =============================================================================
   MonetaDemo - 05: read-only stored procedures (schema ai_api)
   These are what the REST API calls for its GET methods. Rules for all of them:
     * validate parameters and THROW 5xxxx with a clear message (the API turns it into 400)
     * always paged or capped - never "return the whole table"
     * search text is matched literally (ai_api.fn_LikePattern), never concatenated into SQL
   Error numbers: 50001 paging, 50002 invalid value, 50003 period, 50004 not found.
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO

/* ---------------------------------------------------------------- contragents */
CREATE OR ALTER PROCEDURE ai_api.usp_GetContragents
    @Search          NVARCHAR(100) = NULL,   -- part of code, name, EIK or VAT number
    @ContragentType  CHAR(1)       = NULL,   -- C customers, S suppliers (both include type B)
    @City            NVARCHAR(100) = NULL,
    @OnlyActive      BIT           = 1,
    @Page            INT           = 1,
    @PageSize        INT           = 50
AS
BEGIN
    SET NOCOUNT ON;
    IF @Page IS NULL OR @Page < 1 OR @PageSize IS NULL OR @PageSize NOT BETWEEN 1 AND 200
        THROW 50001, N'Page must be >= 1 and PageSize between 1 and 200.', 1;
    IF @ContragentType IS NOT NULL AND @ContragentType NOT IN ('C', 'S', 'B')
        THROW 50002, N'ContragentType must be C, S or B.', 1;

    DECLARE @Pattern NVARCHAR(410) = ai_api.fn_LikePattern(@Search);

    SELECT  c.*, COUNT(*) OVER () AS TotalCount
    FROM    ai_api.v_Contragents AS c
    WHERE   (@Pattern IS NULL OR c.Code LIKE @Pattern OR c.Name LIKE @Pattern
                              OR c.EIK LIKE @Pattern OR c.VatNumber LIKE @Pattern)
      AND   (@ContragentType IS NULL OR c.ContragentType = @ContragentType
                                     OR (c.ContragentType = 'B' AND @ContragentType IN ('C', 'S')))
      AND   (@City IS NULL OR c.City = @City)
      AND   (@OnlyActive = 0 OR c.IsActive = 1)
    ORDER BY c.Name
    OFFSET (@Page - 1) * @PageSize ROWS FETCH NEXT @PageSize ROWS ONLY
    OPTION (RECOMPILE);   -- optional filters: plan per call instead of one bad cached plan
END;
GO

CREATE OR ALTER PROCEDURE ai_api.usp_GetContragentByCode
    @Code NVARCHAR(20)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM dbo.Contragents WHERE Code = @Code)
        THROW 50004, N'Contragent not found.', 1;

    DECLARE @From DATE = DATEADD(MONTH, -12, CAST(GETDATE() AS DATE));

    SELECT  v.*,
            stats.SalesNetLast12M,
            stats.InvoicesLast12M,
            stats.LastSaleDate
    FROM    ai_api.v_Contragents AS v
    OUTER APPLY (
        SELECT  CAST(ISNULL(SUM(s.LineNet), 0) AS DECIMAL(18,2)) AS SalesNetLast12M,
                COUNT(DISTINCT CASE WHEN s.DocTypeCode = 'INV' THEN s.DocumentId END) AS InvoicesLast12M,
                MAX(s.DocDate) AS LastSaleDate
        FROM    ai_api.fn_SalesLines(@From, CAST(GETDATE() AS DATE)) AS s
        WHERE   s.ContragentCode = v.Code
    ) AS stats
    WHERE   v.Code = @Code;
END;
GO

/* ------------------------------------------------------------------- articles */
CREATE OR ALTER PROCEDURE ai_api.usp_GetArticles
    @Search       NVARCHAR(100) = NULL,   -- part of code, name or barcode
    @GroupCode    NVARCHAR(20)  = NULL,
    @OnlyInStock  BIT           = 0,
    @OnlyActive   BIT           = 1,
    @Page         INT           = 1,
    @PageSize     INT           = 50
AS
BEGIN
    SET NOCOUNT ON;
    IF @Page IS NULL OR @Page < 1 OR @PageSize IS NULL OR @PageSize NOT BETWEEN 1 AND 200
        THROW 50001, N'Page must be >= 1 and PageSize between 1 and 200.', 1;

    DECLARE @Pattern NVARCHAR(410) = ai_api.fn_LikePattern(@Search);

    SELECT  a.*, COUNT(*) OVER () AS TotalCount
    FROM    ai_api.v_Articles AS a
    WHERE   (@Pattern IS NULL OR a.Code LIKE @Pattern OR a.Name LIKE @Pattern OR a.Barcode LIKE @Pattern)
      AND   (@GroupCode IS NULL OR a.GroupCode = @GroupCode)
      AND   (@OnlyInStock = 0 OR a.StockTotal > 0)
      AND   (@OnlyActive = 0 OR a.IsActive = 1)
    ORDER BY a.Code
    OFFSET (@Page - 1) * @PageSize ROWS FETCH NEXT @PageSize ROWS ONLY
    OPTION (RECOMPILE);
END;
GO

CREATE OR ALTER PROCEDURE ai_api.usp_GetArticleStock
    @Code NVARCHAR(30)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM dbo.Articles WHERE Code = @Code)
        THROW 50004, N'Article not found.', 1;

    SELECT  s.ArticleCode, s.ArticleName, s.Unit, s.WarehouseCode, s.WarehouseName, s.Quantity, s.UpdatedAt
    FROM    ai_api.v_Stock AS s
    WHERE   s.ArticleCode = @Code
    ORDER BY s.WarehouseCode;
END;
GO

/* ------------------------------------------------------------------ documents */
CREATE OR ALTER PROCEDURE ai_api.usp_GetDocuments
    @DateFrom        DATE,
    @DateTo          DATE,
    @DocTypeCode     VARCHAR(10)   = NULL,   -- INV, CRN, ORD, DLV
    @ContragentCode  NVARCHAR(20)  = NULL,
    @Status          CHAR(1)       = NULL,   -- D, C, X
    @Page            INT           = 1,
    @PageSize        INT           = 50
AS
BEGIN
    SET NOCOUNT ON;
    IF @Page IS NULL OR @Page < 1 OR @PageSize IS NULL OR @PageSize NOT BETWEEN 1 AND 200
        THROW 50001, N'Page must be >= 1 and PageSize between 1 and 200.', 1;
    IF @DateFrom IS NULL OR @DateTo IS NULL OR @DateTo < @DateFrom OR DATEDIFF(DAY, @DateFrom, @DateTo) > 366
        THROW 50003, N'DateFrom/DateTo are required, DateTo >= DateFrom, max 366 days.', 1;
    IF @Status IS NOT NULL AND @Status NOT IN ('D', 'C', 'X')
        THROW 50002, N'Status must be D, C or X.', 1;

    SELECT  d.*, COUNT(*) OVER () AS TotalCount
    FROM    ai_api.v_Documents AS d
    WHERE   d.DocDate >= @DateFrom AND d.DocDate <= @DateTo
      AND   (@DocTypeCode IS NULL OR d.DocTypeCode = @DocTypeCode)
      AND   (@ContragentCode IS NULL OR d.ContragentCode = @ContragentCode)
      AND   (@Status IS NULL OR d.Status = @Status)
    ORDER BY d.DocDate DESC, d.DocNumber DESC
    OFFSET (@Page - 1) * @PageSize ROWS FETCH NEXT @PageSize ROWS ONLY
    OPTION (RECOMPILE);
END;
GO

CREATE OR ALTER PROCEDURE ai_api.usp_GetDocument
    @DocTypeCode  VARCHAR(10),
    @DocNumber    VARCHAR(20)
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM ai_api.v_Documents WHERE DocTypeCode = @DocTypeCode AND DocNumber = @DocNumber)
        THROW 50004, N'Document not found.', 1;

    SELECT  d.*
    FROM    ai_api.v_Documents AS d
    WHERE   d.DocTypeCode = @DocTypeCode AND d.DocNumber = @DocNumber;
END;
GO

CREATE OR ALTER PROCEDURE ai_api.usp_GetDocumentLines
    @DocTypeCode  VARCHAR(10),
    @DocNumber    VARCHAR(20)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @DocumentId INT =
        (SELECT DocumentId FROM ai_api.v_Documents WHERE DocTypeCode = @DocTypeCode AND DocNumber = @DocNumber);
    IF @DocumentId IS NULL
        THROW 50004, N'Document not found.', 1;

    SELECT  l.[LineNo], l.ArticleCode, l.ArticleName, l.Unit, l.Quantity, l.UnitPrice,
            l.DiscountPercent, l.VatPercent, l.LineNet, l.LineVat
    FROM    ai_api.v_DocumentLines AS l
    WHERE   l.DocumentId = @DocumentId
    ORDER BY l.[LineNo];
END;
GO

/* -------------------------------------------------------------------- reports */
CREATE OR ALTER PROCEDURE ai_api.usp_SalesReport
    @DateFrom  DATE,
    @DateTo    DATE,
    @GroupBy   VARCHAR(20) = 'article',   -- article | contragent | group | month | city
    @Top       INT         = 20
AS
BEGIN
    SET NOCOUNT ON;
    IF @DateFrom IS NULL OR @DateTo IS NULL OR @DateTo < @DateFrom OR DATEDIFF(DAY, @DateFrom, @DateTo) > 366
        THROW 50003, N'DateFrom/DateTo are required, DateTo >= DateFrom, max 366 days.', 1;
    IF @GroupBy NOT IN ('article', 'contragent', 'group', 'month', 'city')
        THROW 50002, N'GroupBy must be article, contragent, group, month or city.', 1;
    IF @Top IS NULL OR @Top NOT BETWEEN 1 AND 500
        THROW 50001, N'Top must be between 1 and 500.', 1;

    SELECT TOP (@Top)
            k.GroupKey,
            k.GroupLabel,
            COUNT(DISTINCT s.DocumentId)                     AS Documents,
            CAST(SUM(s.Quantity) AS DECIMAL(18,3))           AS Quantity,
            CAST(SUM(s.LineNet) AS DECIMAL(18,2))            AS NetAmount,
            CAST(SUM(s.LineNet + s.LineVat) AS DECIMAL(18,2)) AS GrossAmount
    FROM    ai_api.fn_SalesLines(@DateFrom, @DateTo) AS s
    CROSS APPLY (SELECT
                    CASE @GroupBy WHEN 'article'    THEN s.ArticleCode
                                  WHEN 'contragent' THEN s.ContragentCode
                                  WHEN 'group'      THEN s.GroupCode
                                  WHEN 'city'       THEN ISNULL(s.ContragentCity, N'-')
                                  ELSE CONVERT(CHAR(7), s.DocDate, 126) END AS GroupKey,
                    CASE @GroupBy WHEN 'article'    THEN s.ArticleName
                                  WHEN 'contragent' THEN s.ContragentName
                                  WHEN 'group'      THEN s.GroupName
                                  WHEN 'city'       THEN ISNULL(s.ContragentCity, N'-')
                                  ELSE CONVERT(CHAR(7), s.DocDate, 126) END AS GroupLabel) AS k
    GROUP BY k.GroupKey, k.GroupLabel
    ORDER BY CASE WHEN @GroupBy = 'month' THEN k.GroupKey END ASC,
             SUM(s.LineNet) DESC
    OPTION (RECOMPILE);
END;
GO

/* Lookup lists for filters (document types, article groups, warehouses). */
CREATE OR ALTER PROCEDURE ai_api.usp_GetLookups
AS
BEGIN
    SET NOCOUNT ON;
    SELECT 'doc_type' AS LookupType, Code, Name FROM dbo.DocumentTypes
    UNION ALL
    SELECT 'article_group', Code, Name FROM dbo.ArticleGroups
    UNION ALL
    SELECT 'warehouse', Code, Name FROM dbo.Warehouses
    ORDER BY LookupType, Code;
END;
GO
PRINT 'Stored procedures ready.';
GO
