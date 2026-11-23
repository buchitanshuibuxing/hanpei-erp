"""财务域：账户/汇率/货代/收付款核销/退款/利润/提成/退税/费用/售后索赔。"""
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text

from .base import Base, TS


class BankAccount(Base, TS):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String(64))
    beneficiary = Column(String(255))
    bank_name = Column(String(255))
    bank_address = Column(Text)
    swift = Column(String(64))
    account_no = Column(String(128))
    account_type = Column(String(32))
    memo_requirements = Column(Text)
    is_active = Column(Boolean, default=True)


class ForexRate(Base, TS):
    __tablename__ = "forex_rates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    currency = Column(String(3), nullable=False, index=True)
    rate = Column(Numeric(12, 6), nullable=False)  # 1 外币 = N CNY
    rate_type = Column(String(16), default="QUOTE")
    effective_date = Column(Date, index=True)
    source = Column(String(16), default="MANUAL")


class Forwarder(Base, TS):
    __tablename__ = "forwarders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    contact = Column(String(128))
    phone = Column(String(64))
    remark = Column(Text)


class Payment(Base, TS):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_no = Column(String(64), unique=True, nullable=False, index=True)
    direction = Column(String(8), default="IN")
    method = Column(String(24), default="TT")
    customer_id = Column(Integer, index=True)
    supplier_id = Column(Integer, index=True)
    order_id = Column(Integer, index=True)
    shipment_id = Column(Integer, index=True)
    amount = Column(Numeric(14, 2), default=0)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Numeric(12, 6), default=1)
    base_amount = Column(Numeric(14, 2), default=0)
    bank_account_id = Column(Integer)
    water_bill_no = Column(String(128))
    received_at = Column(DateTime, index=True)
    forwarder_id = Column(Integer)
    fee_amount = Column(Numeric(14, 2), default=0)
    net_amount = Column(Numeric(14, 2), default=0)
    status = Column(String(16), default="UNALLOCATED", index=True)
    approval_status = Column(String(16), default="NONE")
    note = Column(Text)


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    payment_id = Column(Integer, nullable=False, index=True)
    target_type = Column(String(16), default="ORDER")
    target_id = Column(Integer, nullable=False, index=True)
    amount = Column(Numeric(14, 2), default=0)


class Refund(Base, TS):
    __tablename__ = "refunds"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, index=True)
    customer_id = Column(Integer)
    amount = Column(Numeric(14, 2), default=0)
    type = Column(String(16), default="REFUND")
    offset_order_id = Column(Integer)
    reason = Column(Text)
    status = Column(String(16), default="PENDING")


class OrderProfit(Base, TS):
    __tablename__ = "order_profits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    shipment_id = Column(Integer, index=True)
    revenue = Column(Numeric(14, 2), default=0)
    purchase_cost = Column(Numeric(14, 2), default=0)
    freight_share = Column(Numeric(14, 2), default=0)
    commission_fee = Column(Numeric(14, 2), default=0)
    expenses = Column(Numeric(14, 2), default=0)
    rebate = Column(Numeric(14, 2), default=0)
    exchange_gain = Column(Numeric(14, 2), default=0)
    net_profit = Column(Numeric(14, 2), default=0)
    margin_pct = Column(Numeric(8, 4), default=0)
    locked = Column(Boolean, default=False)
    calculated_at = Column(DateTime)
    formula_version = Column(String(16), default="v1")  # P0 补充：口径可追溯
    detail = Column(Text)


class Commission(Base, TS):
    __tablename__ = "commissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, index=True)
    user_name = Column(String(64), index=True)
    order_id = Column(Integer, nullable=False, index=True)
    base_amount = Column(Numeric(14, 2), default=0)
    rate = Column(Numeric(8, 6), default=0.015)
    amount = Column(Numeric(14, 2), default=0)
    period = Column(String(7), index=True)
    status = Column(String(16), default="PENDING")
    note = Column(Text)


class Rebate(Base, TS):
    __tablename__ = "rebates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, index=True)
    order_no = Column(String(64))
    customs_doc_no = Column(String(128))
    invoice_no = Column(String(128))
    purchase_invoice_no = Column(String(128))
    declare_amount = Column(Numeric(14, 2))
    rebate_rate = Column(Numeric(6, 4))
    rebate_amount = Column(Numeric(14, 2), default=0)
    status = Column(String(16), default="PENDING")
    received_at = Column(Date)
    note = Column(Text)


class Expense(Base, TS):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, index=True)
    shipment_id = Column(Integer, index=True)
    type = Column(String(32))
    amount = Column(Numeric(14, 2), default=0)
    currency = Column(String(3), default="CNY")
    exchange_rate = Column(Numeric(12, 6), default=1)
    description = Column(Text)


class AfterSalesClaim(Base, TS):
    """P0 补充：售后索赔轻量版（登记 → 定责 → 退款/冲抵 → 回写利润）。"""
    __tablename__ = "after_sales_claims"
    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_no = Column(String(64), unique=True, nullable=False, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer)
    product_id = Column(Integer)
    qty = Column(Numeric(14, 2), default=0)
    reason = Column(Text)
    responsibility = Column(String(24), default="UNKNOWN")  # SUPPLIER / LOGISTICS / INTERNAL / CUSTOMER
    amount = Column(Numeric(14, 2), default=0)
    currency = Column(String(3), default="USD")
    resolution = Column(String(24), default="PENDING")       # REFUND / OFFSET / REPLACE / REJECT
    status = Column(String(16), default="OPEN")
    resolved_at = Column(DateTime)
