"""GET methods over the real Moneta tables (read-only).

  GET /api/v1/moneta/contragents          customers:read   N_Contragent (search, paging)
  GET /api/v1/moneta/contragents/{id}     customers:read
  GET /api/v1/moneta/items                products:read    N_Item (search, paging)
  GET /api/v1/moneta/items/{id}           products:read
  GET /api/v1/moneta/invoices             reports:read     D_SaleInvoiceHeader (period, contragent, type, paging)
  GET /api/v1/moneta/invoices/{id}        reports:read     header + all D_SaleInvoiceLine rows (master_id)
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import audit
from ..security.ratelimit import client_ip
from ..services import moneta
from .deps import Principal, require

router = APIRouter(prefix="/api/v1/moneta", tags=["moneta"])

Limit = Annotated[int, Query(ge=1, le=moneta.MAX_ROWS)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]
Search = Annotated[str | None, Query(max_length=100)]


def _audit(db: Session, request: Request, p: Principal, action: str, **detail) -> None:
    audit.record(db, action, tenant_id=p.tenant_id, user_id=p.user_id, client_id=p.client_id,
                 ip=client_ip(request), request_id=request.state.request_id, actor=p.actor, **detail)


@router.get("/contragents")
async def list_contragents(request: Request, p: Annotated[Principal, Depends(require("customers:read"))],
                           search: Search = None, limit: Limit = 50, offset: Offset = 0,
                           db: Session = Depends(get_db)):
    result = await run_in_threadpool(moneta.list_rows, "contragents", search=search, limit=limit, offset=offset)
    _audit(db, request, p, "moneta.contragents.list", search=bool(search), returned=len(result["rows"]))
    return result


@router.get("/contragents/{contragent_id}")
async def get_contragent(contragent_id: str, request: Request,
                         p: Annotated[Principal, Depends(require("customers:read"))], db: Session = Depends(get_db)):
    row = await run_in_threadpool(moneta.get_by_id, "contragents", contragent_id[:64])
    _audit(db, request, p, "moneta.contragents.get", id=contragent_id[:64])
    return row


@router.get("/items")
async def list_items(request: Request, p: Annotated[Principal, Depends(require("products:read"))],
                     search: Search = None, limit: Limit = 50, offset: Offset = 0, db: Session = Depends(get_db)):
    result = await run_in_threadpool(moneta.list_rows, "items", search=search, limit=limit, offset=offset)
    _audit(db, request, p, "moneta.items.list", search=bool(search), returned=len(result["rows"]))
    return result


@router.get("/items/{item_id}")
async def get_item(item_id: str, request: Request,
                   p: Annotated[Principal, Depends(require("products:read"))], db: Session = Depends(get_db)):
    row = await run_in_threadpool(moneta.get_by_id, "items", item_id[:64])
    _audit(db, request, p, "moneta.items.get", id=item_id[:64])
    return row


@router.get("/invoices")
async def list_invoices(request: Request, p: Annotated[Principal, Depends(require("reports:read"))],
                        date_from: date | None = None, date_to: date | None = None,
                        contragent_id: Annotated[str | None, Query(max_length=64)] = None,
                        document_type: Annotated[int | None, Query(ge=0, le=255)] = None,
                        search: Search = None, limit: Limit = 50, offset: Offset = 0, db: Session = Depends(get_db)):
    filters, order = await run_in_threadpool(moneta.invoice_filters, date_from, date_to, contragent_id, document_type)
    result = await run_in_threadpool(moneta.list_rows, "invoices", search=search, filters=filters, order_by=order,
                                     limit=limit, offset=offset)
    _audit(db, request, p, "moneta.invoices.list", date_from=date_from, date_to=date_to,
           contragent=contragent_id, returned=len(result["rows"]))
    return result


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, request: Request,
                      p: Annotated[Principal, Depends(require("reports:read"))], db: Session = Depends(get_db)):
    result = await run_in_threadpool(moneta.invoice_with_lines, invoice_id[:64])
    _audit(db, request, p, "moneta.invoices.get", id=invoice_id[:64], lines=result["line_count"])
    return result
