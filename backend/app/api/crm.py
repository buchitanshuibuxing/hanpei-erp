"""CRM 与线索：客户/联系人/协议价/供应商/跟进/线索池与客户交接。"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.audit import audit
from ..core.crud import (as_dict, create_resource, delete_resource,
                         list_resource, update_resource)
from ..core.deps import Actor, check_parent_owner, require
from ..core.normalize import normalize_oe
from ..core.numbering import next_no
from ..core.utils import num, row_dict
from ..db import get_db
from ..models.crm import (Customer, CustomerContact, CustomerPriceItem,
                          FollowUp, Lead, Supplier, SupplierPriceHistory)
from ..models.sales import Quotation, SalesOrder
from ..services.excel import export_excel
from .helpers import xlsx_response

router = APIRouter(prefix="/api", tags=["CRM"])


@router.get("/customers")
def list_customers(request: Request, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    return list_resource(db, Customer, actor, "crm", request,
                         like_fields=("code", "name", "name_ar", "country", "whatsapp"))


@router.post("/customers")
def create_customer(body: dict, actor: Actor = Depends(require("crm", "create")), db=Depends(get_db)):
    payload = dict(body)
    payload.setdefault("code", next_no(db, "CUSTOMER"))
    payload.setdefault("owner_name", actor.name if actor.role == "SALES" else payload.get("owner_name") or "")
    row = create_resource(db, Customer, payload, actor, module="crm")
    db.commit()
    return as_dict(row, "crm", actor)


@router.get("/customers/{cid}")
def get_customer(cid: int, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "客户不存在")
    data = as_dict(c, "crm", actor)
    data["contacts"] = [row_dict(x) for x in db.query(CustomerContact).filter_by(customer_id=cid).all()]
    data["price_items"] = [row_dict(x) for x in db.query(CustomerPriceItem).filter_by(customer_id=cid).all()]
    return data


@router.put("/customers/{cid}")
def update_customer(cid: int, body: dict, actor: Actor = Depends(require("crm", "edit")), db=Depends(get_db)):
    update_resource(db, Customer, cid, body, actor, module="crm")
    db.commit()
    return {"message": "已保存"}


@router.delete("/customers/{cid}")
def delete_customer(cid: int, actor: Actor = Depends(require("crm", "delete")), db=Depends(get_db)):
    delete_resource(db, Customer, cid, actor, module="crm")
    db.commit()
    return {"message": "已删除"}


@router.get("/customers/{cid}/timeline")
def customer_360(cid: int, _=Depends(require("crm", "view")), db=Depends(get_db)):
    """客户 360：跟进 / 报价 / 订单 / 收款 一条时间流。"""
    events = []
    for f in db.query(FollowUp).filter_by(customer_id=cid).all():
        events.append({"at": f.created_at.isoformat() if f.created_at else "", "type": "跟进",
                       "title": f.type or "", "detail": f.content or ""})
    for q in db.query(Quotation).filter_by(customer_id=cid).all():
        events.append({"at": q.created_at.isoformat() if q.created_at else "", "type": "报价",
                       "title": q.quote_no, "detail": f"{q.currency} {num(q.total):,.2f} / {q.status}"})
    for o in db.query(SalesOrder).filter_by(customer_id=cid).all():
        events.append({"at": o.created_at.isoformat() if o.created_at else "", "type": "订单",
                       "title": o.order_no, "detail": f"{o.currency} {num(o.total):,.2f} / {o.status}"})
    from ..models.finance import Payment
    for p in db.query(Payment).filter_by(customer_id=cid).all():
        events.append({"at": p.created_at.isoformat() if p.created_at else "", "type": "收款",
                       "title": p.payment_no, "detail": f"{p.currency} {num(p.amount):,.2f}"})
    events.sort(key=lambda e: e["at"], reverse=True)
    return events


class TransferIn(BaseModel):
    new_owner: str


@router.post("/customers/{cid}/transfer")
def transfer_customer(cid: int, body: TransferIn, actor: Actor = Depends(require("crm", "edit")),
                      db=Depends(get_db)):
    c = db.get(Customer, cid)
    if not c:
        raise HTTPException(404, "客户不存在")
    old = c.owner_name
    c.owner_name = body.new_owner
    # 未结报价/订单跟随客户归属（提成归属边界）
    db.query(Quotation).filter_by(customer_id=cid).update({"owner_name": body.new_owner})
    db.query(SalesOrder).filter_by(customer_id=cid).update({"owner_name": body.new_owner})
    audit(db, actor, "customer.transfer", "customers", cid,
          detail=f"{old} → {body.new_owner}（含未结报价/订单归属）")
    db.commit()
    return {"message": f"已交接给 {body.new_owner}"}


@router.get("/customers/export/all")
def export_customers(actor: Actor = Depends(require("crm", "export")), db=Depends(get_db)):
    rows = db.query(Customer).filter(Customer.deleted_at.is_(None))
    if actor.role == "SALES":
        rows = rows.filter(Customer.owner_name == actor.name)
    rows = rows.all()
    headers = ["编码", "公司名", "国家", "等级", "业务员", "币种", "付款政策", "账期(天)",
               "信用额度", "WhatsApp", "邮箱", "状态"]
    data = [[c.code, c.name, c.country, c.level, c.owner_name, c.currency, c.payment_policy,
             c.payment_terms_days, num(c.credit_limit), c.whatsapp, c.email, c.status] for c in rows]
    return xlsx_response(export_excel(headers, data, "客户"), "客户清单.xlsx")


def _subresource(model, module, request, actor, db, like_fields=()):
    return list_resource(db, model, actor, module, request, like_fields=like_fields)


@router.get("/customer-contacts")
def contacts(request: Request, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    return _subresource(CustomerContact, "crm", request, actor, db, ("name", "phone"))


@router.post("/customer-contacts")
def add_contact(body: dict, actor: Actor = Depends(require("crm", "create")), db=Depends(get_db)):
    check_parent_owner(db, actor, Customer, body.get("customer_id"), "客户")
    row = create_resource(db, CustomerContact, body, actor)
    db.commit()
    return row_dict(row)


@router.delete("/customer-contacts/{rid}")
def del_contact(rid: int, actor: Actor = Depends(require("crm", "edit")), db=Depends(get_db)):
    row = db.get(CustomerContact, rid)
    if not row:
        raise HTTPException(404, "联系人不存在")
    check_parent_owner(db, actor, Customer, row.customer_id, "客户")
    delete_resource(db, CustomerContact, rid, actor)
    db.commit()
    return {"message": "已删除"}


@router.get("/customer-price-items")
def price_items(request: Request, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    return _subresource(CustomerPriceItem, "crm", request, actor, db)


@router.post("/customer-price-items")
def add_price_item(body: dict, actor: Actor = Depends(require("crm", "edit")), db=Depends(get_db)):
    check_parent_owner(db, actor, Customer, body.get("customer_id"), "客户")
    row = create_resource(db, CustomerPriceItem, body, actor)
    db.commit()
    return row_dict(row)


@router.delete("/customer-price-items/{rid}")
def del_price_item(rid: int, actor: Actor = Depends(require("crm", "edit")), db=Depends(get_db)):
    row = db.get(CustomerPriceItem, rid)
    if not row:
        raise HTTPException(404, "协议价不存在")
    check_parent_owner(db, actor, Customer, row.customer_id, "客户")
    delete_resource(db, CustomerPriceItem, rid, actor)
    db.commit()
    return {"message": "已删除"}


@router.get("/suppliers")
def suppliers(request: Request, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    return list_resource(db, Supplier, actor, "crm", request, like_fields=("code", "name"))


@router.post("/suppliers")
def add_supplier(body: dict, actor: Actor = Depends(require("crm", "create")), db=Depends(get_db)):
    row = create_resource(db, Supplier, body, actor)
    db.commit()
    return row_dict(row)


@router.put("/suppliers/{sid}")
def update_supplier(sid: int, body: dict, actor: Actor = Depends(require("crm", "edit")), db=Depends(get_db)):
    update_resource(db, Supplier, sid, body, actor, module="crm")
    db.commit()
    return {"message": "已保存"}


@router.get("/supplier-price-history")
def supplier_prices(request: Request, actor: Actor = Depends(require("purchase", "view")), db=Depends(get_db)):
    return list_resource(db, SupplierPriceHistory, actor, "purchase", request)


@router.get("/follow-ups")
def follow_ups(request: Request, actor: Actor = Depends(require("crm", "view")), db=Depends(get_db)):
    return list_resource(db, FollowUp, actor, "crm", request, like_fields=("content",))


@router.post("/follow-ups")
def add_follow_up(body: dict, actor: Actor = Depends(require("crm", "create")), db=Depends(get_db)):
    row = create_resource(db, FollowUp, body, actor,
                          defaults={"user_name": actor.name, "user_id": actor.id})
    db.commit()
    return row_dict(row)


PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
WHOLESALE_WORDS = ("wholesale", "جملة", "distributor", "dealer", "importer", "تاجر")


@router.post("/leads/parse")
def parse_leads(body: dict, _=Depends(require("lead", "view"))):
    """智能粘贴解析（规则引擎）：电话/WhatsApp/批发商关键词/国家猜测；LLM 引擎由开关控制。"""
    text = str(body.get("text", ""))
    out = []
    for line in [x.strip() for x in text.splitlines() if x.strip()]:
        phone = PHONE_RE.search(line)
        ctype = "WHOLESALE" if any(w in line.lower() for w in WHOLESALE_WORDS) else "UNKNOWN"
        oes = [normalize_oe(x) for x in re.findall(r"[A-Za-z0-9\-]{6,}", line) if normalize_oe(x).isalnum()]
        out.append({"raw": line, "phone": phone.group(1).strip() if phone else "",
                    "customer_type": ctype, "interest_products": oes[:5],
                    "facebook": "facebook.com" in line.lower()})
    return {"items": out, "engine": "RULE"}


@router.get("/leads")
def leads(request: Request, actor: Actor = Depends(require("lead", "view")), db=Depends(get_db)):
    return list_resource(db, Lead, actor, "lead", request,
                         like_fields=("contact_name", "company", "whatsapp", "facebook"))


@router.post("/leads")
def add_lead(body: dict, actor: Actor = Depends(require("lead", "create")), db=Depends(get_db)):
    row = create_resource(db, Lead, body, actor,
                          defaults={"owner_name": actor.name, "owner_user_id": actor.id})
    db.commit()
    return row_dict(row)


@router.post("/leads/batch")
def batch_leads(body: dict, actor: Actor = Depends(require("lead", "create")), db=Depends(get_db)):
    items = body.get("items", [])
    created = 0
    for it in items:
        create_resource(db, Lead, it, actor,
                        defaults={"owner_name": actor.name, "owner_user_id": actor.id})
        created += 1
    db.commit()
    return {"created": created}


@router.put("/leads/{lid}")
def update_lead(lid: int, body: dict, actor: Actor = Depends(require("lead", "edit")), db=Depends(get_db)):
    update_resource(db, Lead, lid, body, actor, module="lead")
    db.commit()
    return {"message": "已保存"}


@router.post("/leads/{lid}/convert")
def convert_lead(lid: int, actor: Actor = Depends(require("lead", "edit")), db=Depends(get_db)):
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "线索不存在")
    if lead.converted_customer_id:
        raise HTTPException(400, "该线索已转化")
    c = Customer(code=next_no(db, "CUSTOMER"), name=lead.company or lead.contact_name or "未命名客户",
                 country=lead.country, whatsapp=lead.whatsapp, email=lead.email,
                 source_channel=lead.channel, source_ref=lead.channel_ref,
                 owner_name=lead.owner_name or actor.name, status="ACTIVE", created_by=actor.name)
    db.add(c)
    db.flush()
    lead.status = "CONVERTED"
    lead.converted_customer_id = c.id
    audit(db, actor, "lead.convert", "leads", lid, detail=f"转客户 {c.code}")
    db.commit()
    return {"customer_id": c.id, "code": c.code}
