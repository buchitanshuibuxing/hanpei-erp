"""交付版增补域：获客海关数据 / 门户账号 / 邮件归档。"""
from sqlalchemy import (Boolean, Column, Date, DateTime, Integer, Numeric,
                        String, Text, UniqueConstraint)

from .base import Base, TS


class CustomsRecord(Base, TS):
    __tablename__ = "customs_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, index=True)
    buyer_name = Column(String(255), index=True)
    buyer_country = Column(String(64))
    supplier_name = Column(String(255))
    product_desc = Column(Text)
    hs_code = Column(String(32))
    amount = Column(Numeric(14, 2))
    source = Column(String(64))
    lead_id = Column(Integer, index=True)


class PortalAccount(Base, TS):
    __tablename__ = "portal_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    failed_count = Column(Integer, default=0)      # P0 补充：门户登录锁定
    locked_until = Column(DateTime)
    last_login_at = Column(DateTime)


class MailMessage(Base, TS):
    __tablename__ = "mail_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    direction = Column(String(8), default="OUT")
    subject = Column(String(512))
    from_addr = Column(String(255))
    to_addr = Column(String(255))
    cc_addr = Column(String(255))
    body_text = Column(Text)
    customer_id = Column(Integer, index=True)
    ref_no = Column(String(64))
    message_id = Column(String(255))
    status = Column(String(16), default="SENT")


class PortalConfirmation(Base, TS):
    """客户门户确认订单：只读门户也可留下可追溯的确认记录，内部可查、可催办。"""
    __tablename__ = "portal_confirmations"
    __table_args__ = (UniqueConstraint("order_id", "customer_id",
                                       name="uq_portal_confirmation_order_customer"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    portal_user = Column(String(64))
    confirmed_at = Column(DateTime, nullable=False, index=True)
    confirm_count = Column(Integer, default=1)
    ip = Column(String(64))
    note = Column(Text)
    status = Column(String(16), default="CONFIRMED")
