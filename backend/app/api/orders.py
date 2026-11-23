"""销售订单：列表/详情/直建/改单留痕/状态机/PI/导出。"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.audit import audit
from ..core.crud import as_dict, list_resource
from ..core.deps import Actor, require
from ..core.numbering import next_no
from ..core.utils import dec, num, row_dict
from ..db import get_db
from ..models.crm import Customer
from ..models.finance import BankAccount
from ..models.sales import (OrderChangeLog, OrderStatusLog, Quotation,
                            SalesOrder, SalesOrderItem)
from ..services.order_state import transition
from ..services.pdf import build_quotation_pdf
from ..services.excel import export_excel
from .helpers import pdf_response, xlsx_response

router = APIRouter(prefix="/api", tags=["销售订单"])


@router.get("/orders")
def list_orders(request: Request, actor: Actor = Depends(require("order", "view")), db=Depends(get_db)):
    return list_resource(db, SalesOrder, actor, "order", request,
                         like_fields=("order_no", "destination"))


@router.post("/orders")
def create_order(body: dict, actor: Actor = Depends(require("order", "create")), db=Depends(get_db)):
    payload = dict(body)
    items = payload.pop("items", [])
    c = db.get(Customer, int(payload.get("customer_id") or 0))
    if not c:
        raise HTTPException(400, "请选择有效客户")
    payload.setdefault("order_no", next_no(db, "ORDER"))
    payload.setdefault("owner_name", actor.name)
    payload.setdefault("currency", c.currency or "USD")
    payload.setdefault("trade_terms", c.trade_terms or "FOB")
    payload.setdefault("status", "PENDING_DEPOSIT")
    payload.setdefault("due_date", date.today())
    o = SalesOrder(**{k: v for k, v in payload.items() if hasattr(SalesOrder, k)})
    o.created_by = actor.name
    db.add(o)
    db.flush()
    for idx, it in enumerate(items, 1):
        qty, price = dec(it.get("qty") or 1), dec(it.get("unit_price") or 0)
        db.add(SalesOrderItem(order_id=o.id, line_no=idx, product_id=it.get("product_id"),
                              oe_no=it.get("oe_no", ""), name_snapshot=it.get("name_snapshot", ""),
                              package_snapshot=it.get("package_snapshot", ""),
                              unit=it.get("unit", "PCS"), qty=qty, unit_price=price,
                              amount=qty * price, cost_snapshot=it.get("cost_snapshot"),
                              created_by=actor.name))
    db.flush()
    o.subtotal = sum(dec(i.amount) for i in db.query(SalesOrderItem).filter_by(order_id=o.id).all())
    o.total = o.subtotal - dec(o.discount)
    o.deposit_amount = o.total * Decimal("0.3")
    o.balance_amount = o.total - o.deposit_amount
    audit(db, actor, "order.create", "sales_orders", o.id, detail=f"直建订单 {o.order_no}")
    db.commit()
    return {"id": o.id, "order_no": o.order_no, "total": float(o.total)}


@router.get("/orders/export/all")
def export_orders(actor: Actor = Depends(require("order", "export")), db=Depends(get_db)):
    rows = db.query(SalesOrder).filter(SalesOrder.deleted_at.is_(None)).all()
    headers = ["订单号", "客户", "业务员", "币种", "总额", "已收", "状态", "交期", "账期起算日"]
    from ..services.order_state import received_total
    data = []
    for o in rows:
        c = db.get(Customer, o.customer_id)
        data.append([o.order_no, c.name if c else "", o.owner_name, o.currency, num(o.total),
                     float(received_total(db, o.id)), o.status,
                     str(o.delivery_date or ""), str(o.due_date or "")])
    return xlsx_response(export_excel(headers, data, "订单"), "订单清单.xlsx")


@router.get("/orders/{oid}")
def get_order(oid: int, actor: Actor = Depends(require("order", "view")), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o:
        raise HTTPException(404, "订单不存在")
    from ..core.deps import check_owner
    check_owner(o, actor)
    from ..services.order_state import received_total
    from ..models.shipping import Shipment
    data = as_dict(o, "order", actor)
    data["items"] = [row_dict(i, ["cost_snapshot"] if actor.role == "SALES" else [])
                     for i in db.query(SalesOrderItem).filter_by(order_id=oid).order_by(SalesOrderItem.line_no).all()]
    data["status_logs"] = [row_dict(x) for x in db.query(OrderStatusLog).filter_by(order_id=oid).all()]
    data["change_logs"] = [row_dict(x) for x in db.query(OrderChangeLog).filter_by(order_id=oid).all()]
    data["shipments"] = [row_dict(x) for x in db.query(Shipment).filter_by(order_id=oid).all()]
    data["received_amount"] = float(received_total(db, oid))
    return data


@router.put("/orders/{oid}")
def update_order(oid: int, body: dict, actor: Actor = Depends(require("order", "edit")), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o:
        raise HTTPException(404, "订单不存在")
    for key in ("unit_price", "qty", "delivery_date", "total", "discount"):
        if key in body and str(body[key]) != str(getattr(o, key, "")):
            db.add(OrderChangeLog(created_at=datetime.utcnow(), order_id=oid, field=key,
                                  old_value=str(getattr(o, key, "")), new_value=str(body[key]),
                                  operator_name=actor.name))
    items = body.pop("items", None)
    for k, v in body.items():
        if hasattr(SalesOrder, k) and k not in ("id", "order_no", "created_at"):
            setattr(o, k, v)
    if items is not None:
        db.query(SalesOrderItem).filter_by(order_id=oid).delete()
        for idx, it in enumerate(items, 1):
            qty, price = dec(it.get("qty") or 1), dec(it.get("unit_price") or 0)
            db.add(SalesOrderItem(order_id=oid, line_no=idx, product_id=it.get("product_id"),
                                  oe_no=it.get("oe_no", ""), name_snapshot=it.get("name_snapshot", ""),
                                  package_snapshot=it.get("package_snapshot", ""),
                                  unit=it.get("unit", "PCS"), qty=qty, unit_price=price,
                                  amount=qty * price, created_by=actor.name))
        db.flush()
        o.total = sum(dec(i.amount) for i in db.query(SalesOrderItem).filter_by(order_id=oid).all())
    audit(db, actor, "order.update", "sales_orders", oid, detail="修改订单")
    db.commit()
    return {"message": "已保存"}


class StatusIn(BaseModel):
    status: str
    note: str = ""


@router.post("/orders/{oid}/status")
def set_status(oid: int, body: StatusIn, actor: Actor = Depends(require("order", "edit")), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o:
        raise HTTPException(404, "订单不存在")
    transition(db, o, body.status, actor, "MANUAL", note=body.note)
    audit(db, actor, "order.status", "sales_orders", oid, detail=f"{o.status}（人工）")
    db.commit()
    return {"status": o.status}


@router.delete("/orders/{oid}")
def cancel_order(oid: int, reason: str = "", actor: Actor = Depends(require("order", "edit")), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o:
        raise HTTPException(404, "订单不存在")
    o.deleted_at = datetime.utcnow()
    o.status = "CANCELLED"
    audit(db, actor, "order.cancel", "sales_orders", oid, detail=reason or "取消订单")
    db.commit()
    return {"message": "订单已取消"}


@router.get("/orders/{oid}/pdf")
def order_pi(oid: int, _=Depends(require("order", "export")), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o:
        raise HTTPException(404, "订单不存在")
    bank = db.query(BankAccount).filter_by(is_active=True).first()
    items = db.query(SalesOrderItem).filter_by(order_id=oid).order_by(SalesOrderItem.line_no).all()
    content = build_quotation_pdf(db, o, db.get(Customer, o.customer_id), items, bank, is_pi=True)
    return pdf_response(content, f"{o.order_no}_PI.pdf")


@router.get("/order-status-logs")
def status_logs(request: Request, _=Depends(require("order", "view")), db=Depends(get_db)):
    return list_resource(db, OrderStatusLog, Actor(role="ADMIN"), "order", request)
