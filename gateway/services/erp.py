"""Business logic. The single place that touches ERP tables.

To connect the real Moneta database, re-implement these functions against
Moneta's tables / views / stored procedures; the API, MCP server and
security layers stay unchanged. Every function takes ``tenant_id`` from the
verified token and filters on it.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import extract, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api import schemas as s
from ..config import get_settings
from ..models import Customer, Order, OrderLine, Product

CENT = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def _like(term: str) -> str:
    # escape LIKE wildcards so user input is matched literally
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ------------------------------------------------------------------ reports
def sales_report(db: Session, tenant_id: int, date_from: date, date_to: date, group_by: str, top: int) -> s.SalesReport:
    if date_to < date_from:
        raise HTTPException(422, "date_to must be on or after date_from")
    if (date_to - date_from).days > 366:
        raise HTTPException(422, "Maximum report period is 366 days")
    start, end = datetime.combine(date_from, time.min), datetime.combine(date_to + timedelta(days=1), time.min)

    base = (
        select()
        .select_from(OrderLine)
        .join(Order, Order.id == OrderLine.order_id)
        .join(Product, Product.id == OrderLine.product_id)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.tenant_id == tenant_id, Order.created_at >= start, Order.created_at < end,
               Order.status != "cancelled")
    )
    gross_expr = OrderLine.line_net * (1 + OrderLine.vat_rate / 100)
    measures = (
        func.count(func.distinct(Order.id)).label("orders"),
        func.sum(OrderLine.quantity).label("quantity"),
        func.sum(OrderLine.line_net).label("net"),
        func.sum(gross_expr).label("gross"),
    )
    if group_by == "product":
        keys = (Product.sku, Product.name)
    elif group_by == "customer":
        keys = (Customer.code, Customer.name)
    elif group_by == "category":
        keys = (Product.category, Product.category)  # NULL -> "Uncategorised" below (portable GROUP BY)
    else:  # month
        y, m = extract("year", Order.created_at), extract("month", Order.created_at)
        keys = (y, m)

    stmt = base.add_columns(*keys, *measures).group_by(*keys).order_by(func.sum(OrderLine.line_net).desc()).limit(top)
    rows = []
    for r in db.execute(stmt):
        k, label = r[0], r[1]
        if group_by == "month":
            k = label = f"{int(k):04d}-{int(label):02d}"
        elif group_by == "category" and k is None:
            k = label = "Uncategorised"
        rows.append(s.SalesReportRow(key=str(k), label=str(label), orders=r.orders, quantity=int(r.quantity or 0),
                                     net=_q(Decimal(r.net or 0)), gross=_q(Decimal(r.gross or 0))))
    if group_by == "month":
        rows.sort(key=lambda x: x.key)

    totals = db.execute(base.add_columns(func.count(func.distinct(Order.id)), func.sum(OrderLine.line_net),
                                         func.sum(gross_expr))).one()
    return s.SalesReport(date_from=date_from, date_to=date_to, group_by=group_by, currency="EUR", rows=rows,
                         order_count=totals[0] or 0, total_net=_q(Decimal(totals[1] or 0)),
                         total_gross=_q(Decimal(totals[2] or 0)))


# ----------------------------------------------------------------- products
def search_products(db: Session, tenant_id: int, q: str | None, limit: int) -> list[s.ProductOut]:
    stmt = select(Product).where(Product.tenant_id == tenant_id, Product.is_active == true())
    if q:
        stmt = stmt.where(or_(Product.sku.ilike(_like(q), escape="\\"), Product.name.ilike(_like(q), escape="\\")))
    stmt = stmt.order_by(Product.sku).limit(limit)
    return [s.ProductOut.model_validate(p, from_attributes=True) for p in db.execute(stmt).scalars()]


def import_products(db: Session, tenant_id: int, req: s.ProductImportRequest) -> s.ProductImportResult:
    if len(req.items) > get_settings().max_import_rows:
        raise HTTPException(422, "Too many rows")
    skus = [i.sku for i in req.items]
    existing = {
        p.sku.upper(): p
        for p in db.execute(select(Product).where(Product.tenant_id == tenant_id, Product.sku.in_(skus))).scalars()
    }
    result = s.ProductImportResult(dry_run=req.dry_run, created=0, updated=0, skipped=0, rows=[])
    for item in req.items:
        current = existing.get(item.sku.upper())
        if current and req.mode == "create_only":
            result.skipped += 1
            result.rows.append(s.ImportResultRow(sku=item.sku, action="skip", reason="SKU already exists"))
            continue
        if current:
            result.updated += 1
            result.rows.append(s.ImportResultRow(sku=item.sku, action="update"))
            if not req.dry_run:
                for field, value in item.model_dump().items():
                    setattr(current, field, value)
        else:
            result.created += 1
            result.rows.append(s.ImportResultRow(sku=item.sku, action="create"))
            if not req.dry_run:
                db.add(Product(tenant_id=tenant_id, **item.model_dump()))
    if not req.dry_run:
        db.flush()
    return result


# ---------------------------------------------------------------- customers
def search_customers(db: Session, tenant_id: int, q: str | None, limit: int) -> list[s.CustomerOut]:
    stmt = select(Customer).where(Customer.tenant_id == tenant_id)
    if q:
        stmt = stmt.where(or_(Customer.code.ilike(_like(q), escape="\\"), Customer.name.ilike(_like(q), escape="\\")))
    stmt = stmt.order_by(Customer.name).limit(limit)
    return [s.CustomerOut.model_validate(c, from_attributes=True) for c in db.execute(stmt).scalars()]


# ------------------------------------------------------------------- orders
def _order_out(order: Order, replay: bool = False) -> s.OrderOut:
    return s.OrderOut(
        order_number=order.order_number, status=order.status, customer_code=order.customer.code,
        customer_name=order.customer.name, currency=order.currency, total_net=order.total_net,
        total_vat=order.total_vat, total_gross=order.total_gross, idempotent_replay=replay,
        lines=[s.OrderLineOut(sku=ln.product.sku, name=ln.product.name, quantity=ln.quantity,
                              unit_price=ln.unit_price, vat_rate=ln.vat_rate, line_net=ln.line_net)
               for ln in order.lines],
    )


def create_order(db: Session, tenant_id: int, user_id: int, client_id: str, req: s.OrderCreate) -> s.OrderOut:
    cfg = get_settings()
    prior = db.execute(select(Order).where(Order.tenant_id == tenant_id,
                                           Order.idempotency_key == req.idempotency_key)).scalar_one_or_none()
    if prior:
        return _order_out(prior, replay=True)

    customer = db.execute(select(Customer).where(Customer.tenant_id == tenant_id,
                                                 Customer.code == req.customer_code)).scalar_one_or_none()
    if not customer:
        raise HTTPException(404, "Customer not found")

    skus = [ln.sku for ln in req.lines]
    products = {p.sku: p for p in db.execute(select(Product).where(
        Product.tenant_id == tenant_id, Product.sku.in_(skus), Product.is_active == true())).scalars()}
    missing = sorted(set(skus) - set(products))
    if missing:
        raise HTTPException(404, f"Unknown SKU(s): {', '.join(missing)}")

    # Prices always come from the database, never from the AI request.
    order = Order(tenant_id=tenant_id, order_number=f"TMP-{uuid.uuid4().hex[:28]}", customer=customer, status="draft", currency="EUR",
                  notes=req.notes, idempotency_key=req.idempotency_key, created_by_user_id=user_id,
                  created_via_client_id=client_id, total_net=Decimal(0), total_vat=Decimal(0),
                  total_gross=Decimal(0))
    net = vat = Decimal(0)
    for ln in req.lines:
        p = products[ln.sku]
        if ln.quantity > p.stock_qty:
            raise HTTPException(409, f"Insufficient stock for {p.sku} (available {p.stock_qty})")
        line_net = _q(p.unit_price * ln.quantity)
        net += line_net
        vat += _q(line_net * p.vat_rate / 100)
        order.lines.append(OrderLine(product=p, quantity=ln.quantity, unit_price=p.unit_price,
                                     vat_rate=p.vat_rate, line_net=line_net))
    order.total_net, order.total_vat, order.total_gross = net, vat, net + vat
    if order.total_gross > Decimal(str(cfg.max_order_total)):
        raise HTTPException(422, f"Order total exceeds the AI limit of {cfg.max_order_total:.2f}; create it in Moneta")

    db.add(order)
    try:
        db.flush()
    except IntegrityError:  # concurrent request with the same idempotency key
        db.rollback()
        prior = db.execute(select(Order).where(Order.tenant_id == tenant_id,
                                               Order.idempotency_key == req.idempotency_key)).scalar_one()
        return _order_out(prior, replay=True)
    order.order_number = f"AI-{order.created_at:%Y%m%d}-{order.id:06d}"
    db.flush()
    return _order_out(order)
