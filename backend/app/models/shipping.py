"""出运与单证域：批次/明细/拼柜/分箱/运费/单证清单。"""
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, Numeric, String, Text

from .base import Base, TS


class Shipment(Base, TS):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_no = Column(String(64), unique=True, nullable=False, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    batch_seq = Column(Integer, default=1)
    status = Column(String(24), default="BOOKING", index=True)
    etd = Column(Date)
    eta = Column(Date)
    bl_no = Column(String(64))
    carrier = Column(String(128))
    voyage = Column(String(64))
    forwarder_id = Column(Integer)
    total_ctn = Column(Integer, default=0)
    total_weight = Column(Numeric(14, 3), default=0)
    total_cbm = Column(Numeric(14, 6), default=0)
    pl_file_path = Column(String(512))
    collection_flag = Column(Boolean, default=False)
    remark = Column(Text)


class ShipmentItem(Base, TS):
    __tablename__ = "shipment_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(Integer, nullable=False, index=True)
    order_item_id = Column(Integer, index=True)
    product_id = Column(Integer, index=True)
    name_snapshot = Column(String(255))
    oe_no = Column(String(128))
    qty = Column(Numeric(14, 2), default=0)
    ctn_no = Column(String(64))
    amount = Column(Numeric(14, 2), default=0)


class ShipmentContainer(Base, TS):
    __tablename__ = "shipment_containers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(Integer, nullable=False, index=True)
    container_no = Column(String(64))
    container_type = Column(String(16), default="20GP")
    ctn_count = Column(Integer, default=0)
    weight = Column(Numeric(14, 3), default=0)
    volume = Column(Numeric(14, 6), default=0)
    seal_no = Column(String(64))


class ShipmentCarton(Base, TS):
    __tablename__ = "shipment_cartons"
    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(Integer, nullable=False, index=True)
    ctn_no = Column(String(32), nullable=False)
    length = Column(Numeric(10, 2))
    width = Column(Numeric(10, 2))
    height = Column(Numeric(10, 2))
    weight = Column(Numeric(12, 3))
    note = Column(Text)


class FreightCost(Base, TS):
    __tablename__ = "freight_costs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(Integer, nullable=False, index=True)
    cost_type = Column(String(24), default="OCEAN")
    amount = Column(Numeric(14, 2), default=0)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Numeric(12, 6), default=1)
    allocation_rule = Column(String(16), default="AMOUNT")
    remark = Column(Text)


class Document(Base, TS):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_type = Column(String(16), nullable=False, index=True)  # PI/CI/PL/...
    order_id = Column(Integer, index=True)
    shipment_id = Column(Integer, index=True)
    doc_no = Column(String(64))
    file_path = Column(String(512))
    status = Column(String(16), default="ISSUED")
    generated_at = Column(DateTime)
    note = Column(Text)
