"""库存服务：全流水可追溯、移动加权成本、订单占用（乐观锁防超卖）。"""
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import update

from ..core.utils import dec
from ..models.inventory import StockBalance, StockMove

OUT_TYPES = {"OUT_SALE", "OUT_RETURN", "SAMPLE_OUT", "TRANSFER_OUT", "ADJUST_OUT"}
IN_TYPES = {"IN_PURCHASE", "IN_RETURN", "SAMPLE_IN", "TRANSFER_IN", "ADJUST_IN"}


def _signed(qty, move_type):
    q = dec(qty)
    if move_type == "ADJUST":
        return q
    if move_type in OUT_TYPES:
        return -abs(q)
    return abs(q)


def _balance(db, product_id, warehouse_id, create=True):
    bal = db.query(StockBalance).filter_by(product_id=product_id, warehouse_id=warehouse_id).first()
    if bal is None and create:
        bal = StockBalance(product_id=product_id, warehouse_id=warehouse_id,
                           qty=0, allocated_qty=0, avg_cost=0, version=0,
                           created_at=datetime.utcnow())
        db.add(bal)
        db.flush()
    return bal


def move(db, *, product_id, warehouse_id, qty, move_type, ref_type=None, ref_id=None,
         ref_no=None, operator="system", cost=None, batch_id=None, note=None, allow_negative=False):
    signed = _signed(qty, move_type)
    if signed == 0:
        raise HTTPException(400, "出入库数量不能为 0")
    bal = _balance(db, product_id, warehouse_id)
    before = dec(bal.qty)
    after = before + signed
    if after < 0 and not allow_negative:
        raise HTTPException(400, f"库存不足：当前 {before}，本次需 {abs(signed)}")
    old_version = bal.version or 0
    values = {"qty": after, "version": old_version + 1, "updated_at": datetime.utcnow()}
    if signed > 0 and cost is not None:
        c = dec(cost)
        values["avg_cost"] = ((before * dec(bal.avg_cost) + signed * c) / after) if after > 0 else c
    res = db.execute(update(StockBalance).where(StockBalance.id == bal.id,
                                                StockBalance.version == old_version).values(**values))
    if res.rowcount != 1:
        raise HTTPException(409, "库存并发冲突，请重试")
    mv = StockMove(created_at=datetime.utcnow(), product_id=product_id,
                   warehouse_id=warehouse_id, move_type=move_type, qty=signed,
                   before_qty=before, after_qty=after, ref_type=ref_type, ref_id=ref_id,
                   ref_no=ref_no, batch_id=batch_id, cost=cost,
                   operator_name=operator, note=note)
    db.add(mv)
    db.flush()
    return mv


def allocate(db, *, product_id, warehouse_id, qty, order_id=None):
    """订单占用：可用量 = qty - allocated_qty；CAS 保证不超卖。"""
    bal = _balance(db, product_id, warehouse_id)
    need = dec(qty)
    old_version = bal.version or 0
    avail = dec(bal.qty) - dec(bal.allocated_qty)
    if avail < need:
        raise HTTPException(400, f"可用库存不足：可用 {avail}，需占用 {need}")
    res = db.execute(update(StockBalance).where(
        StockBalance.id == bal.id, StockBalance.version == old_version
    ).values(allocated_qty=dec(bal.allocated_qty) + need, version=old_version + 1,
             updated_at=datetime.utcnow()))
    if res.rowcount != 1:
        raise HTTPException(409, "库存分配并发冲突，请重试")
    return True


def release(db, *, product_id, warehouse_id, qty):
    bal = _balance(db, product_id, warehouse_id, create=False)
    if bal is None:
        return
    new = max(Decimal("0"), dec(bal.allocated_qty) - dec(qty))
    db.execute(update(StockBalance).where(StockBalance.id == bal.id).values(
        allocated_qty=new, version=(bal.version or 0) + 1, updated_at=datetime.utcnow()))


def available(db, product_id, warehouse_id=1):
    bal = db.query(StockBalance).filter_by(product_id=product_id, warehouse_id=warehouse_id).first()
    return float(dec(bal.qty) - dec(bal.allocated_qty)) if bal else 0.0
