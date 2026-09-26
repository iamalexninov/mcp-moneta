"""Read-only access to real Moneta tables (e.g. the local Test_Ninov sample).

Tables used: N_Contragent, N_Item, D_SaleInvoiceHeader, D_SaleInvoiceLine
(lines link to the header via master_id -> Id).

Column names are read from the database itself (INFORMATION_SCHEMA), so the code
works with the real Moneta structure without hard-coding every column. Safety:
  * table names come from the fixed map below, never from user input;
  * column names come only from the database's own metadata and are [quoted];
  * every value is a bound parameter; lists are always paged (max 200 rows);
  * only SELECT statements; the connection string should use a read-only account.
"""

import base64
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
from urllib.parse import quote_plus

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from ..config import get_settings

TABLES = {
    "contragents": "N_Contragent",
    "items": "N_Item",
    "invoices": "D_SaleInvoiceHeader",
    "invoice_lines": "D_SaleInvoiceLine",
}
ID = "Id"
LINE_MASTER = "master_id"
MAX_ROWS = 200
TEXT_TYPES = {"nvarchar", "varchar", "nchar", "char"}
# text columns whose name contains one of these are searched by the "search" parameter
SEARCHABLE_HINTS = ("name", "code", "bulstat", "eik", "vat", "documentno", "absolute_no", "barcode")


@lru_cache
def engine() -> Engine:
    s = get_settings()
    if not s.erp_odbc:
        raise HTTPException(503, "Moneta database is not configured (set GATEWAY_ERP_ODBC in .env)")
    eng = create_engine("mssql+pyodbc:///?odbc_connect=" + quote_plus(s.erp_odbc), pool_pre_ping=True,
                        pool_size=5, max_overflow=5)

    @event.listens_for(eng, "connect")
    def _timeout(dbapi_conn, _):
        dbapi_conn.timeout = s.erp_query_timeout  # pyodbc query timeout

    return eng


@lru_cache
def columns(key: str) -> dict[str, str]:
    """{column_name: data_type} for one of the known tables, from the database metadata."""
    with engine().connect() as conn:
        rows = conn.execute(
            text("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                 "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"),
            {"t": TABLES[key]},
        ).all()
    if not rows:
        raise HTTPException(503, f"Table dbo.{TABLES[key]} not found in the Moneta database")
    return {r[0]: r[1] for r in rows}


def _col(key: str, name: str) -> str | None:
    """Real column name (case-insensitive match) or None."""
    return next((c for c in columns(key) if c.lower() == name.lower()), None)


def _q(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def _select_list(key: str) -> str:
    # binary columns (images, row versions) are not useful to an AI and are left out
    return ", ".join(_q(c) for c, t in columns(key).items() if t not in ("binary", "varbinary", "image", "timestamp"))


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[") + "%"


def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)          # exact, no float rounding
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, bytes):
        return base64.b64encode(v).decode()
    return v


def _rows(result) -> list[dict]:
    keys = list(result.keys())
    return [{k: _jsonable(v) for k, v in zip(keys, row)} for row in result.all()]


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_ROWS or offset < 0:
        raise HTTPException(400, f"limit must be 1-{MAX_ROWS} and offset >= 0")
    return limit, offset


def search_columns(key: str) -> list[str]:
    return [c for c, t in columns(key).items()
            if t in TEXT_TYPES and any(h in c.lower() for h in SEARCHABLE_HINTS)][:8]


def list_rows(key: str, *, search: str | None = None, filters: dict | None = None,
              order_by: list[str] | None = None, limit: int = 50, offset: int = 0) -> dict:
    """Generic paged SELECT over one of the known tables."""
    limit, offset = _page(limit, offset)
    where, params = [], {"limit": limit, "offset": offset}
    if search:
        cols = search_columns(key)
        if not cols:
            raise HTTPException(400, "This table has no searchable text columns")
        params["search"] = _like(search.strip()[:100])
        where.append("(" + " OR ".join(f"{_q(c)} LIKE :search ESCAPE '\\'" for c in cols) + ")")
    for i, (sql_expr, value) in enumerate((filters or {}).items()):
        where.append(sql_expr.replace(":v", f":f{i}"))
        params[f"f{i}"] = value
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order = ", ".join(order_by or [f"{_q(_col(key, ID) or ID)} DESC"])
    table = "dbo." + _q(TABLES[key])
    with engine().connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}{where_sql}"), params).scalar()
        result = conn.execute(text(f"SELECT {_select_list(key)} FROM {table}{where_sql} ORDER BY {order} "
                                   "OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY"), params)
        rows = _rows(result)
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


def get_by_id(key: str, row_id: str) -> dict:
    id_col = _col(key, ID)
    if not id_col:
        raise HTTPException(500, f"{TABLES[key]} has no {ID} column")
    with engine().connect() as conn:
        rows = _rows(conn.execute(text(f"SELECT {_select_list(key)} FROM dbo.{_q(TABLES[key])} "
                                       f"WHERE {_q(id_col)} = :id"), {"id": row_id}))
    if not rows:
        raise HTTPException(404, f"{TABLES[key]} {row_id} not found")
    return rows[0]


def invoice_filters(date_from: date | None, date_to: date | None, contragent_id: str | None,
                    document_type: int | None) -> tuple[dict, list[str]]:
    """Filters for D_SaleInvoiceHeader, only for columns that exist in this database."""
    filters, order = {}, []
    date_col = _col("invoices", "DocumentDate")
    if (date_from or date_to) and not date_col:
        raise HTTPException(400, "D_SaleInvoiceHeader has no DocumentDate column")
    if date_from:
        filters[f"{_q(date_col)} >= :v"] = date_from
    if date_to:
        filters[f"{_q(date_col)} < DATEADD(DAY, 1, CAST(:v AS DATE))"] = date_to
    if contragent_id:
        c = _col("invoices", "Contragent_Id")
        if not c:
            raise HTTPException(400, "D_SaleInvoiceHeader has no Contragent_Id column")
        filters[f"{_q(c)} = :v"] = contragent_id
    if document_type is not None:
        c = _col("invoices", "DocumentType")
        if not c:
            raise HTTPException(400, "D_SaleInvoiceHeader has no DocumentType column")
        filters[f"{_q(c)} = :v"] = document_type
    if date_col:
        order.append(f"{_q(date_col)} DESC")
    order.append(f"{_q(_col('invoices', ID) or ID)} DESC")
    return filters, order


def invoice_with_lines(invoice_id: str) -> dict:
    header = get_by_id("invoices", invoice_id)
    master = _col("invoice_lines", LINE_MASTER)
    if not master:
        raise HTTPException(500, f"{TABLES['invoice_lines']} has no {LINE_MASTER} column")
    order = _col("invoice_lines", ID) or master
    with engine().connect() as conn:
        lines = _rows(conn.execute(
            text(f"SELECT TOP ({MAX_ROWS * 5}) {_select_list('invoice_lines')} FROM dbo.{_q(TABLES['invoice_lines'])} "
                 f"WHERE {_q(master)} = :id ORDER BY {_q(order)}"), {"id": header.get(_col('invoices', ID))}))
    return {"invoice": header, "lines": lines, "line_count": len(lines)}


def status() -> dict:
    """Connection check: server/database name, row count and columns per table."""
    out = {}
    with engine().connect() as conn:
        out["server"], out["database"] = conn.execute(text("SELECT @@SERVERNAME, DB_NAME()")).one()
        for key, table in TABLES.items():
            try:
                cols = columns(key)
                n = conn.execute(text(f"SELECT COUNT(*) FROM dbo.{_q(table)}")).scalar()
                out[table] = {"rows": n, "columns": len(cols), "searchable": search_columns(key)}
            except HTTPException as e:
                out[table] = {"error": e.detail}
    return out
