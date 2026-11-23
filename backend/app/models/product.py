"""产品域：分类/主表/OE 号/替代关系/图片/附件/水印模板。"""
from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from .base import Base, JSONType, Soft, TS


class Category(Base, TS):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, index=True)
    name = Column(String(128), nullable=False)
    level = Column(Integer, default=1)
    sort = Column(Integer, default=0)


class Product(Base, TS, Soft):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name_cn = Column(String(255))
    name_en = Column(String(255), index=True)
    category_id = Column(Integer, index=True)
    brand_grade = Column(String(32))
    spec_params = Column(JSONType)
    unit = Column(String(16), default="PCS")
    package_type = Column(String(64))
    inner_qty = Column(Integer)
    carton_qty = Column(Integer)
    net_weight = Column(Numeric(12, 3))
    gross_weight = Column(Numeric(12, 3))
    carton_volume = Column(Numeric(12, 6))
    length = Column(Numeric(10, 2))
    width = Column(Numeric(10, 2))
    height = Column(Numeric(10, 2))
    barcode = Column(String(64))
    standard_price = Column(Numeric(14, 2), default=0)
    floor_price = Column(Numeric(14, 2))          # 底价：低于此价触发审批
    cost_price = Column(Numeric(14, 2))           # 预估成本（无采购记录时的兜底）
    currency = Column(String(3), default="USD")
    hs_code = Column(String(32), index=True)      # P0 补充：报关/退税必需
    declare_elements = Column(Text)               # 申报要素
    rebate_rate = Column(Numeric(6, 4))           # 退税率
    safety_stock = Column(Integer, default=0)
    status = Column(String(16), default="ACTIVE", index=True)
    image_path = Column(String(512))


class ProductOeNumber(Base, TS):
    __tablename__ = "product_oe_numbers"
    __table_args__ = (UniqueConstraint("product_id", "oe_no", "oe_type"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    oe_no = Column(String(128), nullable=False)
    oe_norm = Column(String(128), nullable=False, index=True)
    oe_type = Column(String(16), default="OE")  # OE / CROSS / ALT
    is_primary = Column(Boolean, default=False)
    source = Column(String(32), default="MANUAL")


class ProductRelation(Base, TS):
    __tablename__ = "product_relations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    related_product_id = Column(Integer, nullable=False)
    relation_type = Column(String(16), default="ALT")


class ProductImage(Base, TS):
    __tablename__ = "product_images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    source = Column(String(16), default="LOCAL")  # LOCAL / MATERIAL
    material_image_id = Column(String(128))
    file_path = Column(String(512))
    thumb_path = Column(String(512))
    is_main = Column(Boolean, default=False)
    filename = Column(String(255))
    license = Column(String(32), default="self")  # 素材库合规字段


class ProductAttachment(Base, TS):
    __tablename__ = "product_attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    doc_type = Column(String(32))  # CATALOG / CERT
    filename = Column(String(255))
    file_path = Column(String(512))


class WatermarkTemplate(Base, TS):
    __tablename__ = "watermark_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    owner_name = Column(String(64))
    scope = Column(String(16), default="COMPANY")
    content_text = Column(Text)
    logo_path = Column(String(512))
    position = Column(String(32), default="bottom-right")
    opacity = Column(Numeric(4, 2), default=0.5)
    font_size = Column(Integer, default=24)
    color = Column(String(16), default="#FFFFFF")
    is_active = Column(Boolean, default=True)
