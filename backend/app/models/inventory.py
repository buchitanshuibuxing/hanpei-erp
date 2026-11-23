"""库存域：仓库/余额/流水/批次/盘点（v2.1）。"""
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from .base import Base, TS


class Warehouse(Base, TS):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    type = Column(String(16), default="FINISHED")
    address = Column(String(255))
    is_active = Column(String(1), default="1")


class StockBalance(Base, TS):
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    warehouse_id = Column(Integer, nullable=False, index=True)
    qty = Column(Numeric(14, 2), default=0)
    allocated_qty = Column(Numeric(14, 2), default=0)
    avg_cost = Column(Numeric(14, 4), default=0)
    version = Column(Integer, default=0)  # P0 补充：库存分配乐观锁


class StockMove(Base):
    __tablename__ = "stock_moves"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    warehouse_id = Column(Integer, nullable=False, index=True)
    move_type = Column(String(24), nullable=False, index=True)
    qty = Column(Numeric(14, 2), nullable=False)
    before_qty = Column(Numeric(14, 2))
    after_qty = Column(Numeric(14, 2))
    ref_type = Column(String(32), index=True)
    ref_id = Column(Integer)
    ref_no = Column(String(64))
    batch_id = Column(Integer)
    cost = Column(Numeric(14, 4))
    operator_name = Column(String(64))
    note = Column(Text)


class StockBatch(Base, TS):
    __tablename__ = "stock_batches"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    supplier_id = Column(Integer)
    po_item_id = Column(Integer)
    batch_no = Column(String(64), index=True)
    warehouse_id = Column(Integer)
    qty = Column(Numeric(14, 2), default=0)
    received_at = Column(DateTime)
    quality_status = Column(String(16), default="OK")


class Stocktake(Base, TS):
    __tablename__ = "stocktakes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    take_no = Column(String(64), unique=True, nullable=False, index=True)
    warehouse_id = Column(Integer, nullable=False)
    status = Column(String(16), default="DRAFT")
    note = Column(Text)
    confirmed_at = Column(DateTime)


class StocktakeItem(Base, TS):
    __tablename__ = "stocktake_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stocktake_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    book_qty = Column(Numeric(14, 2), default=0)
    real_qty = Column(Numeric(14, 2))
    diff_qty = Column(Numeric(14, 2))
    note = Column(Text)
