/* =============================================================================
   MonetaDemo - 03: functions + internal procedures
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO

/* Total stock of an article across all warehouses. */
CREATE OR ALTER FUNCTION dbo.fn_ArticleStock (@ArticleId INT)
RETURNS DECIMAL(18,3)
WITH SCHEMABINDING
AS
BEGIN
    RETURN ISNULL((SELECT SUM(s.Quantity) FROM dbo.Stock AS s WHERE s.ArticleId = @ArticleId), 0);
END;
GO

/* Recalculate a document's totals from its lines (call after changing lines). */
CREATE OR ALTER PROCEDURE dbo.usp_RecalcDocumentTotals
    @DocumentId INT
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE d
       SET TotalNet = ISNULL(x.Net, 0),
           TotalVat = ISNULL(x.Vat, 0)
      FROM dbo.Documents AS d
      OUTER APPLY (SELECT SUM(l.LineNet) AS Net, SUM(l.LineVat) AS Vat
                     FROM dbo.DocumentLines AS l
                    WHERE l.DocumentId = d.Id) AS x
     WHERE d.Id = @DocumentId;
END;
GO

/* Turns user search text into a safe LIKE pattern: %, _ and [ are matched literally.
   NULL/blank input -> NULL (meaning "no filter"). */
CREATE OR ALTER FUNCTION ai_api.fn_LikePattern (@Search NVARCHAR(100))
RETURNS NVARCHAR(410)
AS
BEGIN
    IF @Search IS NULL OR LTRIM(RTRIM(@Search)) = N'' RETURN NULL;
    RETURN N'%' + REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(@Search)), N'[', N'[[]'), N'%', N'[%]'), N'_', N'[_]') + N'%';
END;
GO

/* Every sales line in turnover (confirmed invoices and credit notes) in a period.
   Credit notes come back with negative quantity/amounts. Inline TVF: the optimizer
   expands it like a view, so it stays fast. */
CREATE OR ALTER FUNCTION ai_api.fn_SalesLines (@DateFrom DATE, @DateTo DATE)
RETURNS TABLE
AS
RETURN
    SELECT  d.Id              AS DocumentId,
            d.DocDate,
            dt.Code           AS DocTypeCode,
            d.DocNumber,
            c.Code            AS ContragentCode,
            c.Name            AS ContragentName,
            c.City            AS ContragentCity,
            a.Code            AS ArticleCode,
            a.Name            AS ArticleName,
            g.Code            AS GroupCode,
            g.Name            AS GroupName,
            l.Quantity * dt.SignFactor AS Quantity,
            l.LineNet  * dt.SignFactor AS LineNet,
            l.LineVat  * dt.SignFactor AS LineVat
    FROM    dbo.Documents     AS d
    JOIN    dbo.DocumentTypes AS dt ON dt.Id = d.DocTypeId
    JOIN    dbo.DocumentLines AS l  ON l.DocumentId = d.Id
    JOIN    dbo.Contragents   AS c  ON c.Id = d.ContragentId
    JOIN    dbo.Articles      AS a  ON a.Id = l.ArticleId
    JOIN    dbo.ArticleGroups AS g  ON g.Id = a.GroupId
    WHERE   dt.CountsInTurnover = 1
      AND   d.Status = 'C'
      AND   d.DocDate >= @DateFrom
      AND   d.DocDate <= @DateTo;
GO
PRINT 'Functions ready.';
GO
