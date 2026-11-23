"""交付版增补域：获客海关数据 / 门户账号 / 邮件归档。"""
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text

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
