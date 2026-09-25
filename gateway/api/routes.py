"""REST API v1: the only way AI agents reach ERP data.

Three core methods:
  GET  /api/v1/reports/sales      reports:read
  POST /api/v1/products/import    products:write
  POST /api/v1/orders             orders:write
Support lookups (used by the AI to find valid SKUs / customers):
  GET  /api/v1/products           products:read
  GET  /api/v1/customers          customers:read
  GET  /api/v1/me                 any valid token
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import audit
from ..security.ratelimit import client_ip
from ..services import erp
from . import schemas as s
from .deps import Principal, get_principal, require

router = APIRouter(prefix="/api/v1", tags=["erp"])


def _audit(db: Session, request: Request, p: Principal, action: str, **detail) -> None:
    audit.record(db, action, tenant_id=p.tenant_id, user_id=p.user_id, client_id=p.client_id,
                 ip=client_ip(request), request_id=request.state.request_id, actor=p.actor, **detail)


@router.get("/me")
def me(p: Annotated[Principal, Depends(get_principal)]):
    return {"user_id": p.user_id, "tenant_id": p.tenant_id, "role": p.role, "client_id": p.client_id,
            "scopes": sorted(p.scopes)}


@router.get("/reports/sales", response_model=s.SalesReport)
def sales_report(
    request: Request,
    p: Annotated[Principal, Depends(require("reports:read"))],
    date_from: date,
    date_to: date,
    group_by: Literal["product", "customer", "category", "month"] = "product",
    top: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
):
    report = erp.sales_report(db, p.tenant_id, date_from, date_to, group_by, top)
    _audit(db, request, p, "api.reports.sales", date_from=date_from, date_to=date_to, group_by=group_by)
    return report


@router.get("/products", response_model=list[s.ProductOut])
def list_products(
    request: Request,
    p: Annotated[Principal, Depends(require("products:read"))],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    db: Session = Depends(get_db),
):
    return erp.search_products(db, p.tenant_id, q, limit)


@router.post("/products/import", response_model=s.ProductImportResult)
def import_products(
    request: Request,
    body: s.ProductImportRequest,
    p: Annotated[Principal, Depends(require("products:write"))],
    db: Session = Depends(get_db),
):
    result = erp.import_products(db, p.tenant_id, body)
    _audit(db, request, p, "api.products.import", dry_run=body.dry_run, mode=body.mode,
           created=result.created, updated=result.updated, skipped=result.skipped)
    return result


@router.get("/customers", response_model=list[s.CustomerOut])
def list_customers(
    p: Annotated[Principal, Depends(require("customers:read"))],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    db: Session = Depends(get_db),
):
    return erp.search_customers(db, p.tenant_id, q, limit)


@router.post("/orders", response_model=s.OrderOut, status_code=201)
def create_order(
    request: Request,
    body: s.OrderCreate,
    p: Annotated[Principal, Depends(require("orders:write"))],
    db: Session = Depends(get_db),
):
    order = erp.create_order(db, p.tenant_id, p.user_id, p.client_id, body)
    _audit(db, request, p, "api.orders.create", order=order.order_number, total=order.total_gross,
           replay=order.idempotent_replay)
    return order
