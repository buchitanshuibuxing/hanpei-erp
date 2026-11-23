"""采购域：采购单/行、采购退货单/行（v2.1）。"""
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text

from .base import Base, TS


class PurchaseOrder(Base, TS):
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    po_no = Column(String(64), unique=True, nullable=False, index=True)
    supplier_id = Column(Integer, nullable=False, index=True)
    order_id = Column(Integer, index=True)
    currency = Column(String(3), default="CNY")
    exchange_rate = Column(Numeric(12, 6), default=1)
    total = Column(Numeric(14, 2), default=0)
    payment_method = Column(String(16), default="PREPAY")
    expected_date = Column(DateTime)
    status = Column(String(24), default="DRAFT", index=True)
    approved_by = Column(String(64))
    warehouse_id = Column(Integer)
    remark = Column(Text)


class PurchaseOrderItem(Base, TS):
    __tablename__ = "purchase_order_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    po_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    name_snapshot = Column(String(255))
    qty = Column(Numeric(14, 2), default=0)
    price = Column(Numeric(14, 4), default=0)
    amount = Column(Numeric(14, 2), default=0)
    qty_received = Column(Numeric(14, 2), default=0)
    batch_no = Column(String(64))


class PurchaseReturn(Base, TS):
    __tablename__ = "purchase_returns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    return_no = Column(String(64), unique=True, nullable=False, index=True)
    purchase_order_id = Column(Integer, index=True)
    supplier_id = Column(Integer)
    warehouse_id = Column(Integer)
    status = Column(String(16), default="DRAFT")
    note = Column(Text)
    confirmed_at = Column(DateTime)


class PurchaseReturnItem(Base, TS):
    __tablename__ = "purchase_return_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_return_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    name_snapshot = Column(String(255))
    qty = Column(Numeric(14, 2), default=0)
    price = Column(Numeric(14, 4), default=0)
    amount = Column(Numeric(14, 2), default=0)
