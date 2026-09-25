"""Strict request/response models. ``extra="forbid"`` rejects unknown fields,
and every field has explicit bounds, so an AI (or attacker) cannot smuggle
unexpected data into the database."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(v: str) -> str:
    return _CONTROL.sub("", v).strip()


CleanStr = Annotated[str, AfterValidator(_clean)]
Sku = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=2000)


# ------------------------------------------------------------------ reports
class SalesReportRow(BaseModel):
    key: str
    label: str
    orders: int
    quantity: int
    net: Decimal
    gross: Decimal


class SalesReport(BaseModel):
    date_from: date
    date_to: date
    group_by: str
    currency: str
    rows: list[SalesReportRow]
    total_net: Decimal
    total_gross: Decimal
    order_count: int


# ----------------------------------------------------------------- products
class ProductIn(Strict):
    sku: Sku
    name: CleanStr = Field(min_length=1, max_length=200)
    description: CleanStr | None = Field(default=None, max_length=2000)
    category: CleanStr | None = Field(default=None, max_length=100)
    unit_price: Decimal = Field(ge=0, le=Decimal("10000000"), max_digits=18, decimal_places=2)
    currency: Literal["EUR", "BGN", "USD"] = "EUR"
    vat_rate: Decimal = Field(default=Decimal("20"), ge=0, le=100, max_digits=5, decimal_places=2)
    stock_qty: int = Field(default=0, ge=0, le=10_000_000)


class ProductImportRequest(Strict):
    items: list[ProductIn] = Field(min_length=1, max_length=500)
    mode: Literal["upsert", "create_only"] = "create_only"
    dry_run: bool = True

    @model_validator(mode="after")
    def _unique_skus(self):
        skus = [i.sku.upper() for i in self.items]
        if len(skus) != len(set(skus)):
            raise ValueError("Duplicate SKUs in import")
        return self


class ImportResultRow(BaseModel):
    sku: str
    action: Literal["create", "update", "skip"]
    reason: str | None = None


class ProductImportResult(BaseModel):
    dry_run: bool
    created: int
    updated: int
    skipped: int
    rows: list[ImportResultRow]


class ProductOut(BaseModel):
    sku: str
    name: str
    category: str | None
    unit_price: Decimal
    currency: str
    vat_rate: Decimal
    stock_qty: int


class CustomerOut(BaseModel):
    code: str
    name: str
    city: str | None


# ------------------------------------------------------------------- orders
class OrderLineIn(Strict):
    sku: Sku
    quantity: int = Field(ge=1, le=100_000)


class OrderCreate(Strict):
    customer_code: CleanStr = Field(min_length=1, max_length=32)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)
    notes: CleanStr | None = Field(default=None, max_length=1000)
    # Client-generated key: retrying the same request never creates a duplicate order.
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class OrderLineOut(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    vat_rate: Decimal
    line_net: Decimal


class OrderOut(BaseModel):
    order_number: str
    status: str
    customer_code: str
    customer_name: str
    currency: str
    total_net: Decimal
    total_vat: Decimal
    total_gross: Decimal
    lines: list[OrderLineOut]
    idempotent_replay: bool = False
