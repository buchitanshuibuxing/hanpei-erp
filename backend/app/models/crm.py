"""客商域：客户/联系人/协议价/供应商/线索/跟进/发帖。"""
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text

from .base import Base, JSONType, Soft, TS


class Customer(Base, TS, Soft):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    name_ar = Column(String(255))
    country = Column(String(64))
    city = Column(String(64))
    address = Column(Text)
    level = Column(String(16), default="B")
    source_channel = Column(String(32))
    source_ref = Column(String(128))
    owner_user_id = Column(Integer, index=True)
    owner_name = Column(String(64), index=True)
    currency = Column(String(3), default="USD")
    trade_terms = Column(String(16), default="FOB")
    payment_policy = Column(String(32), default="NEW_DEPOSIT")
    payment_terms_days = Column(Integer, default=0)  # P0 补充：账龄起算依据
    payment_method_default = Column(JSONType)
    credit_limit = Column(Numeric(14, 2), default=0)
    whatsapp = Column(String(64))
    email = Column(String(128))
    status = Column(String(16), default="ACTIVE", index=True)


class CustomerContact(Base, TS):
    __tablename__ = "customer_contacts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    name = Column(String(128))
    title = Column(String(64))
    phone = Column(String(64))
    whatsapp = Column(String(64))
    email = Column(String(128))
    preference_lang = Column(String(16), default="en")
    is_primary = Column(Boolean, default=False)


class CustomerPriceItem(Base, TS):
    __tablename__ = "customer_price_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    price = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), default="USD")
    min_qty = Column(Integer, default=0)
    valid_from = Column(DateTime)
    valid_to = Column(DateTime)


class Supplier(Base, TS, Soft):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    country = Column(String(64))
    contact = Column(String(64))
    phone = Column(String(64))
    email = Column(String(128))
    main_category = Column(String(64))
    payment_method = Column(String(16), default="PREPAY")
    rating_quality = Column(Numeric(3, 1))
    rating_delivery = Column(Numeric(3, 1))
    rating_price = Column(Numeric(3, 1))
    status = Column(String(16), default="ACTIVE")


class SupplierPriceHistory(Base, TS):
    __tablename__ = "supplier_price_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    supplier_id = Column(Integer, index=True)
    price = Column(Numeric(14, 2))
    currency = Column(String(3), default="CNY")
    po_date = Column(DateTime)
    po_no = Column(String(64))


class Lead(Base, TS, Soft):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel = Column(String(32), index=True)
    channel_ref = Column(String(128))
    contact_name = Column(String(128))
    company = Column(String(255))
    phone = Column(String(64))
    whatsapp = Column(String(64))
    facebook = Column(String(255))
    email = Column(String(128))
    country = Column(String(64))
    customer_type = Column(String(16), default="UNKNOWN")
    interest_products = Column(JSONType)
    owner_user_id = Column(Integer)
    owner_name = Column(String(64), index=True)
    status = Column(String(16), default="NEW", index=True)
    converted_customer_id = Column(Integer)
    converted_quotation_id = Column(Integer)
    score = Column(Integer, default=0)
    source = Column(String(32))
    note = Column(Text)


class FollowUp(Base, TS):
    __tablename__ = "follow_ups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, index=True)
    lead_id = Column(Integer, index=True)
    user_id = Column(Integer)
    user_name = Column(String(64))
    type = Column(String(16), default="WHATSAPP")
    content = Column(Text)
    next_follow_at = Column(DateTime)


class SocialPost(Base, TS):
    __tablename__ = "social_posts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel = Column(String(32), default="FACEBOOK")
    post_url = Column(String(512))
    content = Column(Text)
    image_refs = Column(JSONType)
    user_name = Column(String(64))
    posted_at = Column(DateTime)
