"""报价与订单域：报价头/行、订单头/行、状态日志、变更日志。"""
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text

from .base import Base, JSONType, Soft, TS


class Quotation(Base, TS, Soft):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_no = Column(String(64), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    contact_id = Column(Integer)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Numeric(12, 6), default=1)
    trade_terms = Column(String(16), default="FOB")
    loading_port = Column(String(64))
    destination = Column(String(64))
    delivery_days = Column(Integer, default=45)
    payment_terms_json = Column(JSONType)
    bank_account_id = Column(Integer)
    discount_pct = Column(Numeric(6, 2), default=0)
    discount_amount = Column(Numeric(14, 2), default=0)
    subtotal = Column(Numeric(14, 2), default=0)
    total = Column(Numeric(14, 2), default=0)
    valid_until = Column(Date)
    status = Column(String(24), default="DRAFT", index=True)
    version = Column(Integer, default=1)
    parent_quotation_id = Column(Integer)
    sent_at = Column(DateTime)
    sent_channel = Column(String(32))
    footer_note = Column(Text)
    seller_snapshot = Column(JSONType)
    buyer_snapshot = Column(JSONType)
    owner_name = Column(String(64), index=True)
    approved_by = Column(String(64))


class QuotationItem(Base, TS):
    __tablename__ = "quotation_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    quotation_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, default=1)
    product_id = Column(Integer, index=True)
    oe_no = Column(String(128))
    name_snapshot = Column(String(255))
    package_snapshot = Column(String(128))
    unit = Column(String(16), default="PCS")
    qty = Column(Numeric(14, 2), default=0)
    unit_price = Column(Numeric(14, 4), default=0)
    amount = Column(Numeric(14, 2), default=0)
    cost_snapshot = Column(Numeric(14, 4))
    match_status = Column(String(16), default="MATCHED")
    stock_status = Column(String(16), default="OK")
    note = Column(Text)


class SalesOrder(Base, TS, Soft):
    __tablename__ = "sales_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    quotation_id = Column(Integer, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    contact_id = Column(Integer)
    owner_user_id = Column(Integer)
    owner_name = Column(String(64), index=True)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Numeric(12, 6), default=1)
    trade_terms = Column(String(16), default="FOB")
    loading_port = Column(String(64))
    destination = Column(String(64))
    payment_terms_json = Column(JSONType)
    payment_method = Column(String(32), default="TT")
    subtotal = Column(Numeric(14, 2), default=0)
    discount = Column(Numeric(14, 2), default=0)
    total = Column(Numeric(14, 2), default=0)
    deposit_amount = Column(Numeric(14, 2), default=0)
    balance_amount = Column(Numeric(14, 2), default=0)
    status = Column(String(24), default="PENDING_DEPOSIT", index=True)
    delivery_date = Column(Date, index=True)
    due_date = Column(Date, index=True)        # P0 补充：账龄起算日
    invoice_date = Column(Date)
    is_sample = Column(Boolean, default=False)
    sample_free = Column(Boolean, default=False)
    source_channel = Column(String(32))
    source_ref = Column(String(128))
    approved_by = Column(String(64))


class SalesOrderItem(Base, TS):
    __tablename__ = "sales_order_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, default=1)
    product_id = Column(Integer, index=True)
    oe_no = Column(String(128))
    name_snapshot = Column(String(255))
    package_snapshot = Column(String(128))
    unit = Column(String(16), default="PCS")
    qty = Column(Numeric(14, 2), default=0)
    unit_price = Column(Numeric(14, 4), default=0)
    amount = Column(Numeric(14, 2), default=0)
    cost_snapshot = Column(Numeric(14, 4))
    qty_shipped = Column(Numeric(14, 2), default=0)
    qty_invoiced = Column(Numeric(14, 2), default=0)
    hs_code_snapshot = Column(String(32))


class OrderStatusLog(Base):
    __tablename__ = "order_status_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    order_id = Column(Integer, nullable=False, index=True)
    from_status = Column(String(24))
    to_status = Column(String(24))
    trigger = Column(String(16), default="MANUAL")
    ref_id = Column(Integer)
    operator_id = Column(Integer)
    operator_name = Column(String(64))
    note = Column(Text)


class OrderChangeLog(Base):
    __tablename__ = "order_change_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    order_id = Column(Integer, nullable=False, index=True)
    field = Column(String(64))
    old_value = Column(Text)
    new_value = Column(Text)
    operator_name = Column(String(64))
