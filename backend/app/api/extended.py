"""交付版扩展域：客户门户（只读隔离）、邮件归档、海关数据、外部能力开关位。"""
from datetime import datetime

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)

from ..core.audit import audit, notify
from ..core.crud import create_resource, list_resource
from ..core.deps import Actor, portal_actor, require
from ..core.utils import dec, num, row_dict
from ..db import get_db
from ..models.extended import (CustomsRecord, MailMessage, PortalAccount,
                               PortalConfirmation)
from ..models.crm import Customer, Lead
from ..models.finance import Payment, PaymentAllocation, Refund
from ..models.sales import SalesOrder, SalesOrderItem
from ..models.shipping import Document
from ..models.system import FeatureFlag
from ..services.excel import read_excel

router = APIRouter(prefix="/api", tags=["扩展域"])


def _flag(db, code):
    f = db.query(FeatureFlag).filter_by(code=code).first()
    return bool(f and f.enabled)


# ---------------- 客户门户：scope=portal 专用，客户 id 强制隔离 ----------------
@router.get("/portal/profile")
def portal_profile(actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    c = db.get(Customer, actor.customer_id)
    if not c:
        raise HTTPException(404, "客户档案不存在")
    return {"code": c.code, "name": c.name, "country": c.country,
            "currency": c.currency, "whatsapp": c.whatsapp, "email": c.email}


@router.get("/portal/orders")
def portal_orders(actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    rows = db.query(SalesOrder).filter_by(customer_id=actor.customer_id).order_by(SalesOrder.id.desc()).all()
    confirms = {c.order_id: c for c in
                db.query(PortalConfirmation).filter_by(customer_id=actor.customer_id).all()}
    out = []
    for o in rows:
        received = sum(dec(a.amount) for a in
                       db.query(PaymentAllocation).filter_by(target_type="ORDER", target_id=o.id).all())
        cf = confirms.get(o.id)
        out.append({"id": o.id, "order_no": o.order_no, "status": o.status,
                    "currency": o.currency, "total": num(o.total),
                    "received": float(received), "balance": float(dec(o.total) - received),
                    "delivery_date": str(o.delivery_date or ""), "etd": "",
                    "confirmed": bool(cf),
                    "confirmed_at": cf.confirmed_at.isoformat() if cf and cf.confirmed_at else "",
                    "confirm_count": cf.confirm_count if cf else 0})
    return out


@router.get("/portal/orders/{oid}")
def portal_order_detail(oid: int, actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    o = db.get(SalesOrder, oid)
    if not o or o.customer_id != actor.customer_id:
        raise HTTPException(404, "订单不存在")
    data = {k: v for k, v in row_dict(o).items() if k not in ("owner_user_id",)}
    data["items"] = [{"oe_no": i.oe_no, "name": i.name_snapshot, "qty": num(i.qty),
                      "unit_price": num(i.unit_price), "amount": num(i.amount)}
                     for i in db.query(SalesOrderItem).filter_by(order_id=oid).all()]
    return data


@router.get("/portal/documents")
def portal_documents(actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    order_ids = [o.id for o in db.query(SalesOrder).filter_by(customer_id=actor.customer_id).all()]
    if not order_ids:
        return []
    return [{"id": d.id, "doc_type": d.doc_type, "doc_no": d.doc_no, "status": d.status,
             "generated_at": d.generated_at.isoformat() if d.generated_at else ""}
            for d in db.query(Document).filter(Document.order_id.in_(order_ids)).all()]


@router.get("/portal/statement")
def portal_statement(actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    rows = []
    for o in db.query(SalesOrder).filter_by(customer_id=actor.customer_id).all():
        received = sum(dec(a.amount) for a in
                       db.query(PaymentAllocation).filter_by(target_type="ORDER", target_id=o.id).all())
        rows.append({"order_no": o.order_no, "currency": o.currency, "total": num(o.total),
                     "received": float(received), "balance": float(dec(o.total) - received)})
    return {"currency": db.get(Customer, actor.customer_id).currency if db.get(Customer, actor.customer_id) else "USD",
            "rows": rows,
            "balance_total": sum(r["balance"] for r in rows)}


@router.post("/portal/orders/{oid}/confirm")
def portal_confirm(oid: int, request: Request,
                   actor: Actor = Depends(portal_actor), db=Depends(get_db)):
    """门户确认订单：只读原则不变（不改写订单状态/金额），但确认动作本身持久化。"""
    o = db.get(SalesOrder, oid)
    if not o or o.customer_id != actor.customer_id:
        raise HTTPException(404, "订单不存在")
    if o.status == "CANCELLED":
        raise HTTPException(400, "已取消的订单不能确认")
    now = datetime.utcnow()
    ip = request.client.host if request.client else ""
    row = db.query(PortalConfirmation).filter_by(order_id=oid,
                                                  customer_id=actor.customer_id).first()
    if row:
        row.confirm_count = (row.confirm_count or 1) + 1
        row.confirmed_at = now
        row.portal_user = actor.username
        row.ip = ip
        detail = "重复确认"
    else:
        row = PortalConfirmation(order_id=oid, customer_id=actor.customer_id,
                                 portal_user=actor.username, confirmed_at=now,
                                 confirm_count=1, ip=ip, status="CONFIRMED")
        db.add(row)
        if o.owner_name:
            notify(db, o.owner_name, f"客户确认订单 {o.order_no}",
                   f"客户 {actor.name or actor.username} 已在门户确认订单 {o.order_no}，请及时跟进。",
                   ref_type="order", ref_id=oid)
        detail = "首次确认"
    audit(db, actor, "portal.order.confirm", "sales_orders", oid,
          detail=f"{detail} {o.order_no}", ip=ip)
    db.commit()
    return {"order_no": o.order_no, "confirmed_at": now.isoformat(),
            "confirm_count": row.confirm_count, "confirmed": True,
            "message": "已记录客户确认，业务员将收到站内通知"}


@router.get("/portal-confirmations")
def portal_confirmations(request: Request,
                         actor: Actor = Depends(require("order", "view")), db=Depends(get_db)):
    """内部查看客户确认记录（门户令牌不可访问本接口）。"""
    return list_resource(db, PortalConfirmation, actor, "order", request)


@router.get("/portal-accounts")
def portal_accounts(request: Request, actor: Actor = Depends(require("portal", "view")), db=Depends(get_db)):
    data = list_resource(db, PortalAccount, actor, "portal", request, like_fields=("username",))
    for r in data["items"]:
        r.pop("password_hash", None)
    return data


@router.post("/portal-accounts")
def add_portal_account(body: dict, actor: Actor = Depends(require("portal", "create")), db=Depends(get_db)):
    from ..core.security import hash_password
    payload = dict(body)
    pwd = payload.pop("password", "portal123")
    payload["password_hash"] = hash_password(str(pwd))
    row = create_resource(db, PortalAccount, payload, actor)
    db.commit()
    return {"id": row.id, "username": row.username}


# ---------------- 邮件归档 ----------------
@router.get("/mails")
def mails(request: Request, actor: Actor = Depends(require("mail", "view")), db=Depends(get_db)):
    return list_resource(db, MailMessage, actor, "mail", request, like_fields=("subject", "from_addr"))


@router.post("/mails")
def add_mail(body: dict, actor: Actor = Depends(require("mail", "view")), db=Depends(get_db)):
    row = create_resource(db, MailMessage, body, actor)
    db.commit()
    return row_dict(row)


# ---------------- 海关数据 / 获客 ----------------
@router.get("/customs-records")
def customs_records(request: Request, actor: Actor = Depends(require("lead", "view")), db=Depends(get_db)):
    return list_resource(db, CustomsRecord, actor, "lead", request, like_fields=("buyer_name", "product_desc"))


@router.post("/customs-records/import")
async def import_customs(file: UploadFile = File(...),
                         actor: Actor = Depends(require("lead", "create")), db=Depends(get_db)):
    rows, _ = read_excel(await file.read())
    n = 0
    for r in rows:
        buyer = str(r.get("采购商") or r.get("Buyer") or "").strip()
        if not buyer:
            continue
        db.add(CustomsRecord(trade_date=r.get("交易日期") or None,
                             buyer_name=buyer, buyer_country=str(r.get("目的国") or ""),
                             supplier_name=str(r.get("供应商") or ""),
                             product_desc=str(r.get("品名") or ""),
                             hs_code=str(r.get("HS编码") or ""),
                             amount=dec(num(r.get("金额") or 0)),
                             source="IMPORT", created_by=actor.name))
        n += 1
    db.commit()
    return {"imported": n}


@router.post("/customs-records/{rid}/to-lead")
def customs_to_lead(rid: int, actor: Actor = Depends(require("lead", "create")), db=Depends(get_db)):
    r = db.get(CustomsRecord, rid)
    if not r or r.lead_id:
        raise HTTPException(400, "记录不存在或已转线索")
    lead = create_resource(db, Lead, {"company": r.buyer_name, "country": r.buyer_country,
                                      "channel": "CUSTOMS", "channel_ref": str(r.id),
                                      "interest_products": [r.product_desc],
                                      "owner_name": actor.name, "score": 60}, actor)
    db.flush()
    r.lead_id = lead.id
    db.commit()
    return {"lead_id": lead.id}


# ---------------- 默认关闭的外部能力 ----------------
@router.get("/collectors/status")
def collectors_status(_=Depends(require("system", "view")), db=Depends(get_db)):
    return [{"code": f.code, "enabled": bool(f.enabled), "description": f.description}
            for f in db.query(FeatureFlag).order_by(FeatureFlag.code).all()]


@router.get("/mcp/tools")
def mcp_tools(_=Depends(require("system", "view")), db=Depends(get_db)):
    if not _flag(db, "MCP_SERVER"):
        raise HTTPException(403, "MCP 服务未启用（系统管理中开启 MCP_SERVER）")
    return {"write_whitelist": ["save_leads"],
            "readonly": ["search_products", "get_quotation", "get_order", "get_customer",
                         "get_stock", "list_inventory", "finance_overview"],
            "note": "写入仅获客 save_leads，其余全只读；删改单据类工具不存在"}


@router.post("/ocr/recognize")
def ocr_recognize(body: dict, _=Depends(require("quotation", "view")), db=Depends(get_db)):
    if not _flag(db, "OCR_API"):
        raise HTTPException(403, "图片 OCR 未启用；PDF 本地文本解析始终可用")
    raise HTTPException(400, "请先在系统参数配置 ocr_api_url / ocr_api_key")
