/* =============================================================================
   MonetaDemo - 04: views (schema ai_api)
   The gateway reads ERP data ONLY through ai_api objects. Views expose just the
   columns an AI assistant needs; internal columns stay hidden.
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO

CREATE OR ALTER VIEW ai_api.v_Contragents
AS
SELECT  c.Code,
        c.Name,
        c.ContragentType,
        CASE c.ContragentType WHEN 'C' THEN N'Клиент' WHEN 'S' THEN N'Доставчик' ELSE N'Клиент и доставчик' END
                          AS ContragentTypeName,
        c.EIK,
        c.VatNumber,
        c.MOL,
        c.Country,
        c.City,
        c.Address,
        c.Phone,
        c.Email,
        c.PaymentTermDays,
        c.CreditLimit,
        c.IsActive,
        c.UpdatedAt
FROM    dbo.Contragents AS c;
GO

CREATE OR ALTER VIEW ai_api.v_Articles
AS
SELECT  a.Code,
        a.Name,
        g.Code        AS GroupCode,
        g.Name        AS GroupName,
        a.Unit,
        a.Barcode,
        a.SalePrice,
        a.VatPercent,
        CAST(ROUND(a.SalePrice * (100 + a.VatPercent) / 100, 2) AS DECIMAL(18,2)) AS SalePriceWithVat,
        dbo.fn_ArticleStock(a.Id) AS StockTotal,
        a.IsActive,
        a.UpdatedAt
FROM    dbo.Articles      AS a
JOIN    dbo.ArticleGroups AS g ON g.Id = a.GroupId;
GO

CREATE OR ALTER VIEW ai_api.v_Stock
AS
SELECT  a.Code AS ArticleCode,
        a.Name AS ArticleName,
        a.Unit,
        w.Code AS WarehouseCode,
        w.Name AS WarehouseName,
        s.Quantity,
        s.UpdatedAt
FROM    dbo.Stock      AS s
JOIN    dbo.Articles   AS a ON a.Id = s.ArticleId
JOIN    dbo.Warehouses AS w ON w.Id = s.WarehouseId;
GO

CREATE OR ALTER VIEW ai_api.v_Documents
AS
SELECT  d.Id            AS DocumentId,
        dt.Code         AS DocTypeCode,
        dt.Name         AS DocTypeName,
        d.DocNumber,
        d.DocDate,
        c.Code          AS ContragentCode,
        c.Name          AS ContragentName,
        w.Code          AS WarehouseCode,
        d.Status,
        CASE d.Status WHEN 'D' THEN N'Чернова' WHEN 'C' THEN N'Потвърден' ELSE N'Анулиран' END AS StatusName,
        d.PaymentMethod,
        d.DueDate,
        d.TotalNet,
        d.TotalVat,
        d.TotalGross,
        d.Notes
FROM    dbo.Documents     AS d
JOIN    dbo.DocumentTypes AS dt ON dt.Id = d.DocTypeId
JOIN    dbo.Contragents   AS c  ON c.Id = d.ContragentId
JOIN    dbo.Warehouses    AS w  ON w.Id = d.WarehouseId;
GO

CREATE OR ALTER VIEW ai_api.v_DocumentLines
AS
SELECT  l.DocumentId,
        l.[LineNo],
        a.Code  AS ArticleCode,
        a.Name  AS ArticleName,
        a.Unit,
        l.Quantity,
        l.UnitPrice,
        l.DiscountPercent,
        l.VatPercent,
        l.LineNet,
        l.LineVat
FROM    dbo.DocumentLines AS l
JOIN    dbo.Articles      AS a ON a.Id = l.ArticleId;
GO
PRINT 'Views ready.';
GO
