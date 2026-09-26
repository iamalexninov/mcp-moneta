/* =============================================================================
   MonetaDemo - 06: demo data (ALL FICTIONAL - names, EIKs, phones, e-mails)
   Document dates are relative to today, so reports always have recent data.
   Runs once: skipped when documents already exist (99_drop_database.sql to rebuild).
   ============================================================================= */
USE MonetaDemo;
GO
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;   -- same as SSMS defaults; required by filtered/computed-column indexes
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF EXISTS (SELECT 1 FROM dbo.Documents)
BEGIN
    PRINT 'Demo data already present - skipped.';
    RETURN;
END;

BEGIN TRANSACTION;

/* ---- document types ---- */
INSERT dbo.DocumentTypes (Id, Code, Name, IsSale, CountsInTurnover, SignFactor) VALUES
 (1, 'INV', N'Фактура',                1, 1,  1),
 (2, 'CRN', N'Кредитно известие',      1, 1, -1),
 (3, 'ORD', N'Поръчка от клиент',      1, 0,  1),
 (4, 'DLV', N'Доставка от доставчик',  0, 0,  1);

/* ---- warehouses ---- */
INSERT dbo.Warehouses (Code, Name, City) VALUES
 (N'SOF', N'Централен склад София', N'София'),
 (N'PLV', N'Склад Пловдив',         N'Пловдив');

/* ---- contragents (fictional) ---- */
INSERT dbo.Contragents (Code, Name, ContragentType, EIK, VatNumber, MOL, City, Address, Phone, Email, PaymentTermDays, CreditLimit) VALUES
 (N'K0001', N'Демо Офис София ООД',            'C', '999000001', 'BG999000001', N'Иван Петров',       N'София',         N'бул. „Демо“ 1',        '+359 000 000 001', 'office@demo-office-sofia.example', 30, 20000),
 (N'K0002', N'Демо Маркет Пловдив ЕООД',       'C', '999000002', 'BG999000002', N'Мария Георгиева',   N'Пловдив',       N'ул. „Демо“ 2',         '+359 000 000 002', 'info@demo-market-plovdiv.example', 15, 10000),
 (N'K0003', N'Демо Марин Сървис Варна АД',     'C', '999000003', 'BG999000003', N'Георги Димитров',   N'Варна',         N'ул. „Демо“ 3',         '+359 000 000 003', 'sales@demo-marine-varna.example',  30, 30000),
 (N'K0004', N'Демо Логистик Бургас ЕООД',      'C', '999000004', 'BG999000004', N'Елена Николова',    N'Бургас',        N'ул. „Демо“ 4',         '+359 000 000 004', 'office@demo-logistic.example',     45, 25000),
 (N'K0005', N'Демо Фуудс Русе ООД',            'C', '999000005', 'BG999000005', N'Петър Иванов',      N'Русе',          N'ул. „Демо“ 5',         '+359 000 000 005', 'info@demo-foods-ruse.example',     14,  8000),
 (N'K0006', N'Демо Агро Стара Загора ЕООД',    'C', '999000006', 'BG999000006', N'Стоян Колев',       N'Стара Загора',  N'ул. „Демо“ 6',         '+359 000 000 006', 'agro@demo-agro.example',           30, 15000),
 (N'K0007', N'Демо Медикал Плевен ЕООД',       'C', '999000007', 'BG999000007', N'Анна Стоянова',     N'Плевен',        N'ул. „Демо“ 7',         '+359 000 000 007', 'office@demo-medical.example',      30, 12000),
 (N'K0008', N'Демо Туризъм Велико Търново ООД','C', '999000008', 'BG999000008', N'Николай Тодоров',   N'Велико Търново',N'ул. „Демо“ 8',         '+359 000 000 008', 'booking@demo-tourism.example',     10,  5000),
 (N'K0009', N'Демо Строй Благоевград ЕООД',    'C', '999000009', 'BG999000009', N'Димитър Ангелов',   N'Благоевград',   N'ул. „Демо“ 9',         '+359 000 000 009', 'office@demo-stroy.example',        60, 40000),
 (N'K0010', N'Демо Пекарни Шумен ООД',         'C', '999000010', 'BG999000010', N'Весела Маринова',   N'Шумен',         N'ул. „Демо“ 10',        '+359 000 000 010', 'orders@demo-bakery.example',        7,  6000),
 (N'K0011', N'Демо Текстил Хасково ЕООД',      'C', '999000011', 'BG999000011', N'Красимир Василев',  N'Хасково',       N'ул. „Демо“ 11',        '+359 000 000 011', 'info@demo-textile.example',        30, 10000),
 (N'K0012', N'Демо Инженеринг Габрово АД',     'C', '999000012', 'BG999000012', N'Йордан Христов',    N'Габрово',       N'ул. „Демо“ 12',        '+359 000 000 012', 'office@demo-engineering.example',  30, 35000),
 (N'K0013', N'Демо Ресторанти София ООД',      'C', '999000013', 'BG999000013', N'Десислава Попова',  N'София',         N'ул. „Демо“ 13',        '+359 000 000 013', 'manager@demo-restaurants.example', 14,  9000),
 (N'K0014', N'Демо Училище Варна',             'C', '999000014', NULL,          N'Росица Атанасова',  N'Варна',         N'ул. „Демо“ 14',        '+359 000 000 014', 'school@demo-school.example',        0,  NULL),
 (N'D0001', N'Демо Дистрибуция Канцелария ООД','S', '999000101', 'BG999000101', N'Христо Кирилов',    N'София',         N'ул. „Демо“ 101',       '+359 000 000 101', 'supply@demo-office-distribution.example', 30, NULL),
 (N'D0002', N'Демо ИТ Импорт ЕООД',            'S', '999000102', 'BG999000102', N'Борислав Янев',     N'София',         N'ул. „Демо“ 102',       '+359 000 000 102', 'b2b@demo-it-import.example',       30, NULL),
 (N'D0003', N'Демо Кафе Трейдинг ООД',         'S', '999000103', 'BG999000103', N'Светлана Илиева',   N'Пловдив',       N'ул. „Демо“ 103',       '+359 000 000 103', 'orders@demo-coffee.example',       15, NULL),
 (N'D0004', N'Демо Хигиена ЕООД',              'B', '999000104', 'BG999000104', N'Милен Русев',       N'Бургас',        N'ул. „Демо“ 104',       '+359 000 000 104', 'office@demo-hygiene.example',      30, 5000);

UPDATE dbo.Contragents SET IsActive = 0 WHERE Code = N'K0011';   -- one inactive contragent for filter tests

/* ---- article groups + articles ---- */
INSERT dbo.ArticleGroups (Code, Name) VALUES
 (N'KAN', N'Канцеларски материали'),
 (N'IT',  N'ИТ аксесоари'),
 (N'KAF', N'Кафе и напитки'),
 (N'HIG', N'Хигиена и почистване');

INSERT dbo.Articles (Code, Name, GroupId, Unit, Barcode, PurchasePrice, SalePrice, VatPercent)
SELECT v.Code, v.Name, g.Id, v.Unit, v.Barcode, v.PPrice, v.SPrice, 20
FROM (VALUES
 (N'KAN-001', N'Хартия А4 80 г/м², 500 л.',           N'KAN', N'пакет', '3809990000011',  5.20,   7.50),
 (N'KAN-002', N'Химикалка синя, кутия 50 бр.',         N'KAN', N'кутия', '3809990000028', 11.00,  18.00),
 (N'KAN-003', N'Кламери 28 мм, 100 бр.',               N'KAN', N'кутия', '3809990000035',  0.60,   1.20),
 (N'KAN-004', N'Телбод метален 24/6',                  N'KAN', N'бр.',   '3809990000042',  7.80,  12.90),
 (N'KAN-005', N'Класьор 8 см',                         N'KAN', N'бр.',   '3809990000059',  2.10,   3.40),
 (N'KAN-006', N'Тетрадка А5, 100 л.',                  N'KAN', N'бр.',   '3809990000066',  1.20,   2.10),
 (N'KAN-007', N'Маркери за бяла дъска, 4 бр.',         N'KAN', N'к-т',   '3809990000073',  4.10,   6.80),
 (N'IT-001',  N'USB-C кабел 1 м',                      N'IT',  N'бр.',   '3809990000080',  5.50,   9.90),
 (N'IT-002',  N'Безжична мишка',                       N'IT',  N'бр.',   '3809990000097', 14.00,  24.90),
 (N'IT-003',  N'Клавиатура БДС/US',                    N'IT',  N'бр.',   '3809990000103', 23.00,  39.90),
 (N'IT-004',  N'Монитор 27" IPS',                      N'IT',  N'бр.',   '3809990000110',289.00, 389.00),
 (N'IT-005',  N'Стойка за лаптоп',                     N'IT',  N'бр.',   '3809990000127', 27.00,  45.00),
 (N'IT-006',  N'USB флаш памет 64 GB',                 N'IT',  N'бр.',   '3809990000134',  8.20,  14.50),
 (N'IT-007',  N'Уеб камера Full HD',                   N'IT',  N'бр.',   '3809990000141', 49.00,  79.00),
 (N'KAF-001', N'Кафе на зърна 1 кг',                   N'KAF', N'кг',    '3809990000158', 21.00,  32.00),
 (N'KAF-002', N'Мляно кафе 250 г',                     N'KAF', N'бр.',   '3809990000165',  5.40,   8.90),
 (N'KAF-003', N'Хартиени чаши 200 мл, 100 бр.',        N'KAF', N'пакет', '3809990000172',  3.20,   5.60),
 (N'KAF-004', N'Захар на стикове, 500 бр.',            N'KAF', N'кутия', '3809990000189', 11.00,  17.50),
 (N'KAF-005', N'Прясно мляко 1 л',                     N'KAF', N'л',     '3809990000196',  2.10,   3.20),
 (N'KAF-006', N'Минерална вода 0,5 л, 12 бр.',         N'KAF', N'стек',  '3809990000202',  4.30,   7.20),
 (N'KAF-007', N'Чай асорти, 100 пакетчета',            N'KAF', N'кутия', '3809990000219',  8.50,  14.00),
 (N'HIG-001', N'Течен сапун 5 л',                      N'HIG', N'бр.',   '3809990000226', 10.20,  16.90),
 (N'HIG-002', N'Тоалетна хартия, 24 ролки',            N'HIG', N'пакет', '3809990000233', 14.50,  22.50),
 (N'HIG-003', N'Кухненска ролка, 6 бр.',               N'HIG', N'пакет', '3809990000240',  5.90,   9.80),
 (N'HIG-004', N'Препарат за под 1 л',                  N'HIG', N'бр.',   '3809990000257',  3.10,   5.40),
 (N'HIG-005', N'Торби за смет 60 л, 50 бр.',           N'HIG', N'ролка', '3809990000264',  4.60,   7.90),
 (N'HIG-006', N'Дезинфектант 1 л',                     N'HIG', N'бр.',   '3809990000271',  6.80,  11.20),
 (N'HIG-007', N'Кърпи от микрофибър, 5 бр.',           N'HIG', N'пакет', '3809990000288',  5.10,   8.70)
) AS v (Code, Name, GroupCode, Unit, Barcode, PPrice, SPrice)
JOIN dbo.ArticleGroups AS g ON g.Code = v.GroupCode;

UPDATE dbo.Articles SET IsActive = 0 WHERE Code = N'IT-007';   -- one discontinued article

/* ---- stock: deterministic pseudo-random quantities, some zero ---- */
INSERT dbo.Stock (WarehouseId, ArticleId, Quantity)
SELECT w.Id, a.Id,
       CASE WHEN (a.Id + w.Id) % 11 = 0 THEN 0
            WHEN a.Code = N'IT-004' THEN (a.Id * 3 + w.Id * 5) % 12
            ELSE (a.Id * 17 + w.Id * 31) % 240 + 5 END
FROM dbo.Articles AS a CROSS JOIN dbo.Warehouses AS w;

/* ---- documents ---- */
DECLARE @Today DATE = CAST(GETDATE() AS DATE);
DECLARE @CustCount INT = (SELECT COUNT(*) FROM dbo.Contragents WHERE ContragentType IN ('C', 'B'));
DECLARE @SuppCount INT = (SELECT COUNT(*) FROM dbo.Contragents WHERE ContragentType IN ('S', 'B'));

;WITH n AS (
    SELECT TOP (450) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
    FROM sys.all_objects AS a CROSS JOIN sys.all_objects AS b
), cust AS (
    SELECT Id, PaymentTermDays, ROW_NUMBER() OVER (ORDER BY Id) AS rn
    FROM dbo.Contragents WHERE ContragentType IN ('C', 'B')
)
-- 450 invoices spread over the last 365 days (bigger customers get more invoices)
INSERT dbo.Documents (DocTypeId, DocNumber, DocDate, ContragentId, WarehouseId, Status, PaymentMethod, DueDate)
SELECT 1,
       RIGHT('0000000000' + CAST(n.i AS VARCHAR(10)), 10),
       DATEADD(DAY, -((n.i * 37) % 365), @Today),
       c.Id,
       1 + (n.i % 2),
       CASE WHEN n.i % 97 = 0 THEN 'X' ELSE 'C' END,
       CASE n.i % 3 WHEN 0 THEN N'в брой' WHEN 1 THEN N'по банка' ELSE N'с карта' END,
       DATEADD(DAY, c.PaymentTermDays, DATEADD(DAY, -((n.i * 37) % 365), @Today))
FROM n
JOIN cust AS c ON c.rn = CASE WHEN n.i % 5 = 0 THEN 1                       -- K0001 is the biggest customer
                              ELSE ((n.i * 7 + n.i / 11) % @CustCount) + 1 END;

;WITH n AS (
    SELECT TOP (15) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects
)
-- 15 credit notes
INSERT dbo.Documents (DocTypeId, DocNumber, DocDate, ContragentId, WarehouseId, Status, PaymentMethod, Notes)
SELECT 2, RIGHT('0000000000' + CAST(900000 + n.i AS VARCHAR(10)), 10),
       DATEADD(DAY, -((n.i * 23) % 300), @Today),
       inv.ContragentId, inv.WarehouseId, 'C', N'по банка',
       N'Кредитно известие към фактура ' + inv.DocNumber
FROM n
JOIN dbo.Documents AS inv ON inv.DocTypeId = 1 AND inv.DocNumber = RIGHT('0000000000' + CAST(n.i * 29 AS VARCHAR(10)), 10);

;WITH n AS (
    SELECT TOP (25) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects
), cust AS (
    SELECT Id, ROW_NUMBER() OVER (ORDER BY Id) AS rn FROM dbo.Contragents WHERE ContragentType IN ('C', 'B')
)
-- 25 customer orders in the last 30 days (some still drafts)
INSERT dbo.Documents (DocTypeId, DocNumber, DocDate, ContragentId, WarehouseId, Status)
SELECT 3, 'ORD-' + RIGHT('000000' + CAST(n.i AS VARCHAR(6)), 6),
       DATEADD(DAY, -(n.i % 30), @Today), c.Id, 1, CASE WHEN n.i % 3 = 0 THEN 'D' ELSE 'C' END
FROM n JOIN cust AS c ON c.rn = (n.i % @CustCount) + 1;

;WITH n AS (
    SELECT TOP (40) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i FROM sys.all_objects
), supp AS (
    SELECT Id, ROW_NUMBER() OVER (ORDER BY Id) AS rn FROM dbo.Contragents WHERE ContragentType IN ('S', 'B')
)
-- 40 deliveries from suppliers
INSERT dbo.Documents (DocTypeId, DocNumber, DocDate, ContragentId, WarehouseId, Status, PaymentMethod)
SELECT 4, 'DLV-' + RIGHT('000000' + CAST(n.i AS VARCHAR(6)), 6),
       DATEADD(DAY, -((n.i * 9) % 365), @Today), s.Id, 1 + (n.i % 2), 'C', N'по банка'
FROM n JOIN supp AS s ON s.rn = (n.i % @SuppCount) + 1;

/* ---- document lines: 1-5 per document, prices from the article card ---- */
DECLARE @ArtCount INT = (SELECT COUNT(*) FROM dbo.Articles);

;WITH art AS (
    SELECT Id, SalePrice, PurchasePrice, VatPercent, GroupId, ROW_NUMBER() OVER (ORDER BY Id) AS rn FROM dbo.Articles
)
INSERT dbo.DocumentLines (DocumentId, [LineNo], ArticleId, Quantity, UnitPrice, DiscountPercent, VatPercent)
SELECT d.Id, k.n, a.Id,
       CASE d.DocTypeId WHEN 2 THEN 1                               -- credit note: 1 unit returned
                        WHEN 4 THEN ((d.Id + k.n * 3) % 10 + 1) * 10  -- deliveries: bigger quantities
                        ELSE (d.Id + k.n * 3) % 10 + 1 END,
       CASE WHEN d.DocTypeId = 4 THEN a.PurchasePrice ELSE a.SalePrice END,
       CASE WHEN d.DocTypeId IN (1, 3) AND (d.Id + k.n * 3) % 10 + 1 >= 8 THEN 5 ELSE 0 END,
       a.VatPercent
FROM dbo.Documents AS d
CROSS JOIN (VALUES (1), (2), (3), (4), (5)) AS k (n)
JOIN art AS a ON a.rn = ((d.Id * 13 + k.n * 5) % @ArtCount) + 1
WHERE k.n <= CASE d.DocTypeId WHEN 2 THEN 1 ELSE (d.Id % 5) + 1 END;

/* ---- document totals (same logic as dbo.usp_RecalcDocumentTotals, set-based) ---- */
UPDATE d
   SET TotalNet = x.Net, TotalVat = x.Vat
  FROM dbo.Documents AS d
  JOIN (SELECT DocumentId, SUM(LineNet) AS Net, SUM(LineVat) AS Vat
          FROM dbo.DocumentLines GROUP BY DocumentId) AS x ON x.DocumentId = d.Id;

COMMIT TRANSACTION;

SELECT 'Contragents' AS [Table], COUNT(*) AS [Rows] FROM dbo.Contragents
UNION ALL SELECT 'Articles', COUNT(*) FROM dbo.Articles
UNION ALL SELECT 'Stock', COUNT(*) FROM dbo.Stock
UNION ALL SELECT 'Documents', COUNT(*) FROM dbo.Documents
UNION ALL SELECT 'DocumentLines', COUNT(*) FROM dbo.DocumentLines;
PRINT 'Demo data loaded.';
GO
