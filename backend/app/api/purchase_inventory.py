"""采购 + 库存：采购建议、到货入库、采购退货、盘点调账、期初导入、流水与预警。"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel

from ..core.audit import audit
from ..core.crud import create_resource, list_resource, update_resource
from ..core.deps import Actor, require
from ..core.numbering import next_no
from ..core.utils import dec, num, paged, row_dict
from ..db import get_db
from ..models.crm import Supplier, SupplierPriceHistory
from ..models.finance import Payment
from ..models.system import ApprovalRequest
from ..models.inventory import (StockBalance, StockBatch, StockMove, Stocktake,
                                StocktakeItem, Warehouse)
from ..models.product import Product
from ..models.purchase import (PurchaseOrder, PurchaseOrderItem,
                               PurchaseReturn, PurchaseReturnItem)
from ..models.sales import SalesOrder, SalesOrderItem
from ..services import stock as stock_svc
from ..services.excel import export_excel, read_excel
from .helpers import xlsx_response

router = APIRouter(prefix="/api", tags=["采购与库存"])


# ---------------- 采购建议 ----------------
@router.get("/purchase-suggestions")
def purchase_suggestions(actor: Actor = Depends(require("purchase", "view")), db=Depends(get_db)):
    """需求（未取消/未结案订单） − 可用库存 − 在途采购 = 建议采购量。"""
    active = ("PENDING_DEPOSIT", "PREPARING", "PENDING_BALANCE", "READY_SHIP", "PARTIAL_SHIPPED")
    demand = {}
    rows = (db.query(SalesOrderItem)
            .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
            .filter(SalesOrder.status.in_(active)).all())
    for it in rows:
        if it.product_id:
            demand[it.product_id] = demand.get(it.product_id, Decimal("0")) + dec(it.qty) - dec(it.qty_shipped)
    # 已下单未到货的采购量，避免重复生成采购建议
    open_po_ids = [p.id for p in db.query(PurchaseOrder).filter(
        PurchaseOrder.status.notin_(("RECEIVED", "CANCELLED", "CLOSED"))).all()]
    in_transit = {}
    if open_po_ids:
        for it in db.query(PurchaseOrderItem).filter(PurchaseOrderItem.po_id.in_(open_po_ids)).all():
            left = max(Decimal("0"), dec(it.qty) - dec(it.qty_received))
            in_transit[it.product_id] = in_transit.get(it.product_id, Decimal("0")) + left
    out = []
    for pid, need in demand.items():
        if need <= 0:
            continue
        p = db.get(Product, pid)
        bal = db.query(StockBalance).filter_by(product_id=pid).first()
        on_hand = dec(bal.qty) - dec(bal.allocated_qty) if bal else Decimal("0")
        transit = in_transit.get(pid, Decimal("0"))
        qty = max(Decimal("0"), need - on_hand - transit)
        if qty > 0:
            out.append({"product_id": pid, "code": p.code if p else "",
                        "name": (p.name_en or p.name_cn) if p else "",
                        "demand": float(need), "on_hand": float(on_hand),
                        "in_transit": float(transit), "suggest_qty": float(qty),
                        "last_cost": float(dec(bal.avg_cost) if bal else 0)})
    return out


# ---------------- 采购单 ----------------
@router.get("/purchase-orders")
def list_pos(request: Request, actor: Actor = Depends(require("purchase", "view")), db=Depends(get_db)):
    return list_resource(db, PurchaseOrder, actor, "purchase", request, like_fields=("po_no",))


@router.post("/purchase-orders")
def create_po(body: dict, actor: Actor = Depends(require("purchase", "create")), db=Depends(get_db)):
    payload = dict(body)
    items = payload.pop("items", [])
    payload.setdefault("po_no", next_no(db, "PURCHASE"))
    payload.setdefault("warehouse_id", 1)
    po = create_resource(db, PurchaseOrder, payload, actor, module="purchase")
    total = Decimal("0")
    for it in items:
        qty, price = dec(it.get("qty") or 0), dec(it.get("price") or 0)
        db.add(PurchaseOrderItem(po_id=po.id, product_id=int(it.get("product_id") or 0),
                                 name_snapshot=it.get("name_snapshot", ""), qty=qty,
                                 price=price, amount=qty * price, created_by=actor.name))
        total += qty * price
    po.total = total
    db.commit()
    return {"id": po.id, "po_no": po.po_no, "total": float(total)}


@router.get("/purchase-orders/{pid}")
def get_po(pid: int, actor: Actor = Depends(require("purchase", "view")), db=Depends(get_db)):
    po = db.get(PurchaseOrder, pid)
    if not po:
        raise HTTPException(404, "采购单不存在")
    data = row_dict(po)
    data["items"] = [row_dict(i) for i in db.query(PurchaseOrderItem).filter_by(po_id=pid).all()]
    return data


class ReceiveIn(BaseModel):
    item_id: int
    qty: float
    quality_status: str = "OK"


@router.post("/purchase-orders/{pid}/receive")
def receive_po(pid: int, body: ReceiveIn, actor: Actor = Depends(require("purchase", "edit")), db=Depends(get_db)):
    """分批到货入库：库存流水 + 批次 + 移动加权成本 + 供应商价格历史。"""
    po = db.get(PurchaseOrder, pid)
    it = db.get(PurchaseOrderItem, body.item_id)
    if not po or not it or it.po_id != pid:
        raise HTTPException(404, "采购单或明细不存在")
    remain = dec(it.qty) - dec(it.qty_received)
    if dec(body.qty) > remain:
        raise HTTPException(400, f"到货数量超过未收数量 {remain}")
    wh = int(po.warehouse_id or 1)
    batch_no = f"{po.po_no}-{it.id}"
    batch = StockBatch(product_id=it.product_id, supplier_id=po.supplier_id,
                       po_item_id=it.id, batch_no=batch_no, warehouse_id=wh,
                       qty=dec(body.qty), received_at=datetime.utcnow(),
                       quality_status=body.quality_status, created_at=datetime.utcnow())
    db.add(batch)
    db.flush()
    stock_svc.move(db, product_id=it.product_id, warehouse_id=wh, qty=dec(body.qty),
                   move_type="IN_PURCHASE", ref_type="PURCHASE", ref_id=pid,
                   ref_no=po.po_no, operator=actor.name, cost=dec(it.price), batch_id=batch.id,
                   note=f"到货批次 {batch_no}")
    it.qty_received = dec(it.qty_received) + dec(body.qty)
    db.add(SupplierPriceHistory(product_id=it.product_id, supplier_id=po.supplier_id,
                                price=it.price, currency=po.currency,
                                po_date=datetime.utcnow(), po_no=po.po_no, created_at=datetime.utcnow()))
    po.status = "RECEIVED" if all(dec(x.qty) <= dec(x.qty_received)
                                  for x in db.query(PurchaseOrderItem).filter_by(po_id=pid).all()) else "PARTIAL_RECEIVED"
    audit(db, actor, "purchase.receive", "purchase_orders", pid, detail=f"到货 {body.qty}")
    db.commit()
    return {"message": "已入库", "batch_id": batch.id, "status": po.status}


# ---------------- 采购退货（v2.1） ----------------
@router.get("/purchase-returns")
def list_returns(request: Request, actor: Actor = Depends(require("purchase", "view")), db=Depends(get_db)):
    return list_resource(db, PurchaseReturn, actor, "purchase", request, like_fields=("return_no",))


@router.post("/purchase-returns")
def create_return(body: dict, actor: Actor = Depends(require("purchase", "create")), db=Depends(get_db)):
    payload = dict(body)
    items = payload.pop("items", [])
    po_id = payload.get("purchase_order_id")
    if po_id and not items:
        for it in db.query(PurchaseOrderItem).filter_by(po_id=int(po_id)).all():
            items.append({"product_id": it.product_id, "name_snapshot": it.name_snapshot,
                          "qty": float(dec(it.qty_received)), "price": float(dec(it.price))})
    payload.setdefault("return_no", next_no(db, "PURCHASE_RETURN"))
    payload.setdefault("warehouse_id", 1)
    r = create_resource(db, PurchaseReturn, payload, actor, module="purchase")
    for it in items:
        qty, price = dec(it.get("qty") or 0), dec(it.get("price") or 0)
        db.add(PurchaseReturnItem(purchase_return_id=r.id, product_id=int(it.get("product_id") or 0),
                                  name_snapshot=it.get("name_snapshot", ""), qty=qty,
                                  price=price, amount=qty * price, created_by=actor.name))
    db.commit()
    return {"id": r.id, "return_no": r.return_no}


@router.post("/purchase-returns/{rid}/confirm")
def confirm_return(rid: int, actor: Actor = Depends(require("purchase", "approve")), db=Depends(get_db)):
    r = db.get(PurchaseReturn, rid)
    if not r or r.status == "CONFIRMED":
        raise HTTPException(400, "退货单不存在或已确认")
    wh = int(r.warehouse_id or 1)
    total = Decimal("0")
    for it in db.query(PurchaseReturnItem).filter_by(purchase_return_id=rid).all():
        stock_svc.move(db, product_id=it.product_id, warehouse_id=wh, qty=-dec(it.qty),
                       move_type="OUT_RETURN", ref_type="PURCHASE_RETURN", ref_id=rid,
                       ref_no=r.return_no, operator=actor.name, note="采购退货出库")
        total += dec(it.amount)
    # 自动生成 REFUND 付款单 + 对应审批单，审批中心可见可批，避免孤儿 PENDING 单据
    pay = Payment(payment_no=next_no(db, "PAYMENT"), direction="OUT", method="REFUND",
                  supplier_id=r.supplier_id, amount=total, currency="CNY",
                  exchange_rate=1, base_amount=total, status="UNALLOCATED",
                  approval_status="PENDING", note=f"采购退货 {r.return_no} 自动退款",
                  created_at=datetime.utcnow(), created_by=actor.name)
    db.add(pay)
    db.flush()
    db.add(ApprovalRequest(flow_type="PAYMENT", ref_type="payment", ref_id=pay.id,
                           ref_no=pay.payment_no, amount=str(total),
                           requested_by=actor.name, status="PENDING",
                           created_at=datetime.utcnow()))
    r.status, r.confirmed_at = "CONFIRMED", datetime.utcnow()
    audit(db, actor, "purchase_return.confirm", "purchase_returns", rid,
          detail=f"出库并生成退款付款单 {float(total):.2f}")
    db.commit()
    return {"message": "已确认，退款单进入审批流", "total": float(total)}


# ---------------- 库存 ----------------
@router.get("/warehouses")
def warehouses(request: Request, actor: Actor = Depends(require("inventory", "view")), db=Depends(get_db)):
    return list_resource(db, Warehouse, actor, "inventory", request, like_fields=("code", "name"))


@router.post("/warehouses")
def add_warehouse(body: dict, actor: Actor = Depends(require("inventory", "edit")), db=Depends(get_db)):
    row = create_resource(db, Warehouse, body, actor)
    db.commit()
    return row_dict(row)


@router.put("/warehouses/{wid}")
def update_warehouse(wid: int, body: dict, actor: Actor = Depends(require("inventory", "edit")), db=Depends(get_db)):
    if db.query(StockBalance).filter_by(warehouse_id=wid).filter(StockBalance.qty != 0).first():
        raise HTTPException(400, "该仓库仍有库存，不能停用；请先调拨")
    update_resource(db, Warehouse, wid, body, actor, module="inventory")
    db.commit()
    return {"message": "已保存"}


@router.get("/stock-balances")
def stock_balances(request: Request, actor: Actor = Depends(require("inventory", "view")), db=Depends(get_db)):
    data = list_resource(db, StockBalance, actor, "inventory", request)
    for row in data["items"]:
        p = db.get(Product, row["product_id"])
        row["product_code"] = p.code if p else ""
        row["product_name"] = (p.name_en or p.name_cn) if p else ""
        row["available_qty"] = num(row["qty"]) - num(row["allocated_qty"])
        row["warning"] = "LOW" if p and num(row["qty"]) < num(p.safety_stock) else "OK"
    return data


@router.get("/stock-moves")
def stock_moves(request: Request, actor: Actor = Depends(require("inventory", "view")), db=Depends(get_db)):
    return list_resource(db, StockMove, actor, "inventory", request)


@router.get("/stock-batches")
def stock_batches(request: Request, actor: Actor = Depends(require("inventory", "view")), db=Depends(get_db)):
    return list_resource(db, StockBatch, actor, "inventory", request)


@router.get("/stock/export")
def export_stock(actor: Actor = Depends(require("inventory", "export")), db=Depends(get_db)):
    headers = ["产品编码", "品名", "仓库", "库存", "已分配", "可用", "移动加权成本"]
    rows = []
    for b in db.query(StockBalance).all():
        p, w = db.get(Product, b.product_id), db.get(Warehouse, b.warehouse_id)
        rows.append([p.code if p else "", (p.name_en or p.name_cn) if p else "",
                     w.name if w else "", num(b.qty), num(b.allocated_qty),
                     num(b.qty) - num(b.allocated_qty), num(b.avg_cost)
                     if actor.role not in ("SALES",) else ""])
    return xlsx_response(export_excel(headers, rows, "库存"), "库存余额.xlsx")


@router.post("/stock/initial-import")
async def initial_stock(file: UploadFile = File(...),
                        actor: Actor = Depends(require("inventory", "create")), db=Depends(get_db)):
    rows, _ = read_excel(await file.read())
    imported, errors = 0, []
    for idx, r in enumerate(rows, 2):
        code = str(r.get("产品编码") or r.get("code") or "").strip()
        p = db.query(Product).filter_by(code=code).first()
        if not p:
            errors.append(f"第 {idx} 行：产品编码 {code} 不存在")
            continue
        wh = db.query(Warehouse).filter_by(code=str(r.get("仓库") or "WH01")).first() or db.query(Warehouse).first()
        qty = dec(r.get("库存数量") or r.get("qty") or 0)
        cost = dec(r.get("成本") or r.get("cost") or 0)
        if qty == 0:
            continue
        stock_svc.move(db, product_id=p.id, warehouse_id=wh.id, qty=qty,
                       move_type="IN_PURCHASE", ref_type="INITIAL", ref_no="期初导入",
                       operator=actor.name, cost=cost, allow_negative=True)
        imported += 1
    db.commit()
    return {"imported": imported, "errors": errors}


# ---------------- 盘点（v2.1） ----------------
@router.get("/stocktakes")
def stocktakes(request: Request, actor: Actor = Depends(require("inventory", "view")), db=Depends(get_db)):
    return list_resource(db, Stocktake, actor, "inventory", request, like_fields=("take_no",))


@router.post("/stocktakes")
def create_stocktake(body: dict, actor: Actor = Depends(require("inventory", "create")), db=Depends(get_db)):
    payload = dict(body)
    payload.setdefault("take_no", next_no(db, "STOCKTAKE"))
    t = create_resource(db, Stocktake, payload, actor, module="inventory")
    wh = int(t.warehouse_id or 1)
    for b in db.query(StockBalance).filter_by(warehouse_id=wh).all():
        db.add(StocktakeItem(stocktake_id=t.id, product_id=b.product_id,
                             book_qty=dec(b.qty), created_by=actor.name))
    db.commit()
    return {"id": t.id, "take_no": t.take_no}


@router.get("/stocktakes/{tid}")
def get_stocktake(tid: int, _=Depends(require("inventory", "view")), db=Depends(get_db)):
    t = db.get(Stocktake, tid)
    if not t:
        raise HTTPException(404, "盘点单不存在")
    data = row_dict(t)
    data["items"] = [row_dict(i) for i in db.query(StocktakeItem).filter_by(stocktake_id=tid).all()]
    return data


@router.put("/stocktakes/{tid}/items")
def set_stocktake_items(tid: int, body: dict, actor: Actor = Depends(require("inventory", "edit")), db=Depends(get_db)):
    t = db.get(Stocktake, tid)
    if not t or t.status == "CONFIRMED":
        raise HTTPException(400, "盘点单不存在或已确认")
    for it in body.get("items", []):
        row = db.get(StocktakeItem, int(it.get("id") or 0))
        if row and row.stocktake_id == tid:
            row.real_qty = dec(it.get("real_qty")) if it.get("real_qty") not in (None, "") else None
            row.note = it.get("note", "")
    db.commit()
    return {"message": "已保存实盘数"}


@router.post("/stocktakes/{tid}/confirm")
def confirm_stocktake(tid: int, actor: Actor = Depends(require("inventory", "approve")), db=Depends(get_db)):
    t = db.get(Stocktake, tid)
    if not t or t.status == "CONFIRMED":
        raise HTTPException(400, "盘点单不存在或已确认")
    adjusted = 0
    for i in db.query(StocktakeItem).filter_by(stocktake_id=tid).all():
        if i.real_qty is None:
            continue
        diff = dec(i.real_qty) - dec(i.book_qty)
        i.diff_qty = diff
        if diff != 0:
            stock_svc.move(db, product_id=i.product_id, warehouse_id=int(t.warehouse_id or 1),
                           qty=diff, move_type="ADJUST", ref_type="STOCKTAKE", ref_id=tid,
                           ref_no=t.take_no, operator=actor.name,
                           note="盘盈" if diff > 0 else "盘亏", allow_negative=True)
            adjusted += 1
    t.status, t.confirmed_at = "CONFIRMED", datetime.utcnow()
    audit(db, actor, "stocktake.confirm", "stocktakes", tid, detail=f"调账 {adjusted} 行")
    db.commit()
    return {"message": "盘点已确认", "adjusted_lines": adjusted}


@router.get("/stocktakes/{tid}/export")
def export_stocktake(tid: int, _=Depends(require("inventory", "export")), db=Depends(get_db)):
    t = db.get(Stocktake, tid)
    headers = ["产品编码", "品名", "账面", "实盘", "差异", "备注"]
    rows = []
    for i in db.query(StocktakeItem).filter_by(stocktake_id=tid).all():
        p = db.get(Product, i.product_id)
        rows.append([p.code if p else "", (p.name_en or p.name_cn) if p else "",
                     num(i.book_qty), num(i.real_qty), num(i.diff_qty), i.note or ""])
    return xlsx_response(export_excel(headers, rows, "盘点表"), f"{t.take_no if t else '盘点表'}.xlsx")
