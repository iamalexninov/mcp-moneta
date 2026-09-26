/* =============================================================================
   MonetaDemo - 02: tables (schema dbo)
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
SET NOCOUNT ON;
GO

/* ---------- Document types (Фактура, Кредитно известие, Поръчка, Доставка) ---------- */
IF OBJECT_ID(N'dbo.DocumentTypes') IS NULL
CREATE TABLE dbo.DocumentTypes (
    Id          TINYINT       NOT NULL CONSTRAINT PK_DocumentTypes PRIMARY KEY,
    Code        VARCHAR(10)   NOT NULL CONSTRAINT UQ_DocumentTypes_Code UNIQUE,
    Name        NVARCHAR(50)  NOT NULL,
    IsSale      BIT           NOT NULL,   -- 1 = sales side (customers), 0 = purchase side (suppliers)
    CountsInTurnover BIT      NOT NULL,   -- 1 = included in sales reports (invoices, credit notes)
    SignFactor  SMALLINT      NOT NULL    -- +1 normal, -1 credit note (reduces sales)
        CONSTRAINT CK_DocumentTypes_Sign CHECK (SignFactor IN (-1, 1))
);
GO

/* ---------- Contragents (контрагенти): customers and suppliers ---------- */
IF OBJECT_ID(N'dbo.Contragents') IS NULL
CREATE TABLE dbo.Contragents (
    Id              INT            IDENTITY(1,1) NOT NULL CONSTRAINT PK_Contragents PRIMARY KEY,
    Code            NVARCHAR(20)   NOT NULL CONSTRAINT UQ_Contragents_Code UNIQUE,
    Name            NVARCHAR(200)  NOT NULL,
    ContragentType  CHAR(1)        NOT NULL          -- C = customer, S = supplier, B = both
        CONSTRAINT CK_Contragents_Type CHECK (ContragentType IN ('C', 'S', 'B')),
    EIK             VARCHAR(13)    NULL,             -- ЕИК / БУЛСТАТ
    VatNumber       VARCHAR(15)    NULL,             -- ДДС номер, e.g. BG123456789
    MOL             NVARCHAR(100)  NULL,             -- материално отговорно лице
    Country         NVARCHAR(50)   NOT NULL CONSTRAINT DF_Contragents_Country DEFAULT (N'България'),
    City            NVARCHAR(100)  NULL,
    Address         NVARCHAR(250)  NULL,
    Phone           VARCHAR(30)    NULL,
    Email           VARCHAR(254)   NULL,
    PaymentTermDays INT            NOT NULL CONSTRAINT DF_Contragents_Term DEFAULT (0)
        CONSTRAINT CK_Contragents_Term CHECK (PaymentTermDays BETWEEN 0 AND 365),
    CreditLimit     DECIMAL(18,2)  NULL,
    IsActive        BIT            NOT NULL CONSTRAINT DF_Contragents_Active DEFAULT (1),
    CreatedAt       DATETIME2(0)   NOT NULL CONSTRAINT DF_Contragents_Created DEFAULT (SYSUTCDATETIME()),
    UpdatedAt       DATETIME2(0)   NOT NULL CONSTRAINT DF_Contragents_Updated DEFAULT (SYSUTCDATETIME())
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Contragents_Name')
    CREATE INDEX IX_Contragents_Name ON dbo.Contragents (Name);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Contragents_EIK')
    CREATE INDEX IX_Contragents_EIK ON dbo.Contragents (EIK) WHERE EIK IS NOT NULL;
GO

/* ---------- Article groups and articles (стоки) ---------- */
IF OBJECT_ID(N'dbo.ArticleGroups') IS NULL
CREATE TABLE dbo.ArticleGroups (
    Id    INT           IDENTITY(1,1) NOT NULL CONSTRAINT PK_ArticleGroups PRIMARY KEY,
    Code  NVARCHAR(20)  NOT NULL CONSTRAINT UQ_ArticleGroups_Code UNIQUE,
    Name  NVARCHAR(100) NOT NULL
);
GO
IF OBJECT_ID(N'dbo.Articles') IS NULL
CREATE TABLE dbo.Articles (
    Id             INT            IDENTITY(1,1) NOT NULL CONSTRAINT PK_Articles PRIMARY KEY,
    Code           NVARCHAR(30)   NOT NULL CONSTRAINT UQ_Articles_Code UNIQUE,
    Name           NVARCHAR(200)  NOT NULL,
    GroupId        INT            NOT NULL CONSTRAINT FK_Articles_Group REFERENCES dbo.ArticleGroups (Id),
    Unit           NVARCHAR(10)   NOT NULL CONSTRAINT DF_Articles_Unit DEFAULT (N'бр.'),
    Barcode        VARCHAR(20)    NULL,
    PurchasePrice  DECIMAL(18,4)  NOT NULL CONSTRAINT DF_Articles_PPrice DEFAULT (0)
        CONSTRAINT CK_Articles_PPrice CHECK (PurchasePrice >= 0),
    SalePrice      DECIMAL(18,4)  NOT NULL
        CONSTRAINT CK_Articles_SPrice CHECK (SalePrice >= 0),
    VatPercent     DECIMAL(5,2)   NOT NULL CONSTRAINT DF_Articles_Vat DEFAULT (20)
        CONSTRAINT CK_Articles_Vat CHECK (VatPercent BETWEEN 0 AND 100),
    IsActive       BIT            NOT NULL CONSTRAINT DF_Articles_Active DEFAULT (1),
    CreatedAt      DATETIME2(0)   NOT NULL CONSTRAINT DF_Articles_Created DEFAULT (SYSUTCDATETIME()),
    UpdatedAt      DATETIME2(0)   NOT NULL CONSTRAINT DF_Articles_Updated DEFAULT (SYSUTCDATETIME())
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Articles_Group')
    CREATE INDEX IX_Articles_Group ON dbo.Articles (GroupId);
GO

/* ---------- Warehouses and stock (складове и наличности) ---------- */
IF OBJECT_ID(N'dbo.Warehouses') IS NULL
CREATE TABLE dbo.Warehouses (
    Id    INT           IDENTITY(1,1) NOT NULL CONSTRAINT PK_Warehouses PRIMARY KEY,
    Code  NVARCHAR(20)  NOT NULL CONSTRAINT UQ_Warehouses_Code UNIQUE,
    Name  NVARCHAR(100) NOT NULL,
    City  NVARCHAR(100) NULL
);
GO
IF OBJECT_ID(N'dbo.Stock') IS NULL
CREATE TABLE dbo.Stock (
    WarehouseId  INT            NOT NULL CONSTRAINT FK_Stock_Warehouse REFERENCES dbo.Warehouses (Id),
    ArticleId    INT            NOT NULL CONSTRAINT FK_Stock_Article REFERENCES dbo.Articles (Id),
    Quantity     DECIMAL(18,3)  NOT NULL CONSTRAINT DF_Stock_Qty DEFAULT (0),
    UpdatedAt    DATETIME2(0)   NOT NULL CONSTRAINT DF_Stock_Updated DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_Stock PRIMARY KEY (WarehouseId, ArticleId)
);
GO

/* ---------- Documents (документи) and lines ---------- */
IF OBJECT_ID(N'dbo.Documents') IS NULL
CREATE TABLE dbo.Documents (
    Id             INT            IDENTITY(1,1) NOT NULL CONSTRAINT PK_Documents PRIMARY KEY,
    DocTypeId      TINYINT        NOT NULL CONSTRAINT FK_Documents_Type REFERENCES dbo.DocumentTypes (Id),
    DocNumber      VARCHAR(20)    NOT NULL,
    DocDate        DATE           NOT NULL,
    ContragentId   INT            NOT NULL CONSTRAINT FK_Documents_Contragent REFERENCES dbo.Contragents (Id),
    WarehouseId    INT            NOT NULL CONSTRAINT FK_Documents_Warehouse REFERENCES dbo.Warehouses (Id),
    Status         CHAR(1)        NOT NULL CONSTRAINT DF_Documents_Status DEFAULT ('D')
        CONSTRAINT CK_Documents_Status CHECK (Status IN ('D', 'C', 'X')),   -- Draft / Confirmed / Cancelled
    PaymentMethod  NVARCHAR(20)   NULL,          -- в брой, по банка, с карта
    DueDate        DATE           NULL,
    TotalNet       DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Documents_Net DEFAULT (0),
    TotalVat       DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Documents_Vat DEFAULT (0),
    TotalGross     AS (TotalNet + TotalVat) PERSISTED,
    Notes          NVARCHAR(500)  NULL,
    CreatedAt      DATETIME2(0)   NOT NULL CONSTRAINT DF_Documents_Created DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT UQ_Documents_Number UNIQUE (DocTypeId, DocNumber)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Documents_Date')
    CREATE INDEX IX_Documents_Date ON dbo.Documents (DocDate) INCLUDE (DocTypeId, ContragentId, Status, TotalNet, TotalVat);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Documents_Contragent')
    CREATE INDEX IX_Documents_Contragent ON dbo.Documents (ContragentId, DocDate);
GO
IF OBJECT_ID(N'dbo.DocumentLines') IS NULL
CREATE TABLE dbo.DocumentLines (
    Id               INT            IDENTITY(1,1) NOT NULL CONSTRAINT PK_DocumentLines PRIMARY KEY,
    DocumentId       INT            NOT NULL
        CONSTRAINT FK_DocumentLines_Document REFERENCES dbo.Documents (Id) ON DELETE CASCADE,
    [LineNo]         SMALLINT       NOT NULL,
    ArticleId        INT            NOT NULL CONSTRAINT FK_DocumentLines_Article REFERENCES dbo.Articles (Id),
    Quantity         DECIMAL(18,3)  NOT NULL CONSTRAINT CK_DocumentLines_Qty CHECK (Quantity > 0),
    UnitPrice        DECIMAL(18,4)  NOT NULL CONSTRAINT CK_DocumentLines_Price CHECK (UnitPrice >= 0),
    DiscountPercent  DECIMAL(5,2)   NOT NULL CONSTRAINT DF_DocumentLines_Disc DEFAULT (0)
        CONSTRAINT CK_DocumentLines_Disc CHECK (DiscountPercent BETWEEN 0 AND 100),
    VatPercent       DECIMAL(5,2)   NOT NULL,
    LineNet          AS (CAST(ROUND(Quantity * UnitPrice * (100 - DiscountPercent) / 100, 2) AS DECIMAL(18,2))) PERSISTED,
    LineVat          AS (CAST(ROUND(ROUND(Quantity * UnitPrice * (100 - DiscountPercent) / 100, 2) * VatPercent / 100, 2) AS DECIMAL(18,2))) PERSISTED,
    CONSTRAINT UQ_DocumentLines_LineNo UNIQUE (DocumentId, [LineNo])
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_DocumentLines_Article')
    CREATE INDEX IX_DocumentLines_Article ON dbo.DocumentLines (ArticleId) INCLUDE (Quantity, LineNet);
GO
PRINT 'Tables ready.';
GO
