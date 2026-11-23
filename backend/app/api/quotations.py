"""询报价：OE 批量匹配、自动带价、折扣审批、单据快照、QT PDF、发送打点、一键转订单。"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel

from ..core.audit import audit
from ..core.crud import as_dict, list_resource, update_resource
from ..core.deps import Actor, require
from ..core.normalize import normalize_oe, parse_oe_list
from ..core.numbering import next_no
from ..core.settings_service import get, get_float
from ..core.utils import dec, num, row_dict
from ..db import get_db
from ..models.crm import Customer, CustomerPriceItem
from ..models.finance import BankAccount, ForexRate
from ..models.product import Product, ProductOeNumber, ProductRelation
from ..models.sales import Quotation, QuotationItem, SalesOrder, SalesOrderItem
from ..models.system import ApprovalRequest
from ..services.excel import export_excel, read_excel
from ..services.pdf import build_quotation_pdf
from .helpers import pdf_response, xlsx_response

router = APIRouter(prefix="/api", tags=["询报价"])

DEFAULT_TERMS = [{"pct": 30, "label": "Deposit"}, {"pct": 70, "label": "Before shipment"}]


def _rate(db, currency):
    r = db.query(ForexRate).filter_by(currency=currency, rate_type="QUOTE").first()
    return dec(r.rate) if r else Decimal("1")


def _price(db, product, customer_id, currency):
    """客户协议价 → 标准价；按报价币种换算（标准价为 USD 基准）。"""
    usd = dec(product.standard_price)
    cp = db.query(CustomerPriceItem).filter_by(customer_id=customer_id,
                                              product_id=product.id).order_by(CustomerPriceItem.min_qty).first()
    if cp:
        usd = dec(cp.price)
    factor = (_rate(db, "USD") / _rate(db, currency)) if _rate(db, currency) else Decimal("1")
    return usd * factor


def _product_by_oe(db, norm):
    hit = db.query(ProductOeNumber).filter_by(oe_norm=norm).first()
    if hit:
        return db.get(Product, hit.product_id), "MATCHED"
    fuzzy = db.query(ProductOeNumber).filter(ProductOeNumber.oe_norm.like(f"%{norm[:6]}%")).first() if len(norm) >= 6 else None
    if fuzzy:
        return db.get(Product, fuzzy.product_id), "SUBSTITUTED"
    rel = db.query(ProductRelation).first()
    if rel:
        return db.get(Product, rel.related_product_id), "SUBSTITUTED"
    return None, "UNMATCHED"


@router.post("/inquiries/match")
def match_inquiry(body: dict, actor: Actor = Depends(require("quotation", "view")), db=Depends(get_db)):
    """粘贴 OE 区域 / Excel 清单 → 三色匹配结果（MATCHED / SUBSTITUTED / UNMATCHED）。"""
    text = str(body.get("text", ""))
    customer_id = int(body.get("customer_id") or 0)
    currency = str(body.get("currency") or "USD")
    raw_items = parse_oe_list(text)
    if body.get("rows"):
        for r in body["rows"]:
            raw_items.append({"raw": str(r.get("oe_no") or r.get("OE") or ""),
                              "norm": normalize_oe(r.get("oe_no") or r.get("OE") or ""),
                              "qty": num(r.get("qty") or r.get("数量") or 1)})
    out = []
    for it in raw_items:
        p, status = _product_by_oe(db, it["norm"])
        line = {"oe_no": it["raw"], "oe_norm": it["norm"], "qty": it.get("qty", 1),
                "match_status": status, "product_id": p.id if p else None}
        if p:
            oe = db.query(ProductOeNumber).filter_by(product_id=p.id, is_primary=True).first()
            line.update({"name_snapshot": p.name_en or p.name_cn,
                         "oe_no": oe.oe_no if oe else it["raw"],
                         "package_snapshot": p.package_type, "unit": p.unit,
                         "unit_price": float(_price(db, p, customer_id, currency)),
                         "cost_snapshot": float(dec(p.cost_price)),
                         "stock_status": "OK"})
            line["amount"] = round(line["unit_price"] * line["qty"], 2)
        out.append(line)
    return {"items": out, "matched": sum(1 for x in out if x["match_status"] == "MATCHED"),
            "total": len(out)}


@router.post("/inquiries/upload")
async def upload_inquiry(file: UploadFile = File(...),
                         actor: Actor = Depends(require("quotation", "view")), db=Depends(get_db)):
    rows, _ = read_excel(await file.read())
    oe_keys = ("OE", "OE NO", "OE NO.", "OE号", "型号", "Part No")
    qty_keys = ("QTY", "数量", "Qty", "QUANTITY")
    text_rows = []
    for r in rows:
        oe = next((r[k] for k in oe_keys if k in r and r[k]), "")
        if not oe:
            continue
        qty = next((r[k] for k in qty_keys if k in r and r[k]), 1)
        text_rows.append({"oe_no": str(oe), "qty": num(qty)})
    return await _match_from_rows(text_rows, actor, db)


async def _match_from_rows(rows, actor, db):
    body = {"rows": rows, "customer_id": 0, "currency": "USD"}
    return match_inquiry(body, actor, db)


def _recalc(q: Quotation, items):
    subtotal = sum(dec(i.amount) for i in items)
    pct = dec(q.discount_pct)
    discount = subtotal * pct / Decimal("100") if pct else dec(q.discount_amount)
    q.subtotal = subtotal
    q.discount_amount = discount
    q.total = subtotal - discount
    return q


@router.get("/quotations")
def list_quotations(request: Request, actor: Actor = Depends(require("quotation", "view")), db=Depends(get_db)):
    return list_resource(db, Quotation, actor, "quotation", request,
                         like_fields=("quote_no", "footer_note"))


@router.post("/quotations")
def create_quotation(body: dict, actor: Actor = Depends(require("quotation", "create")), db=Depends(get_db)):
    payload = dict(body)
    items = payload.pop("items", [])
    customer_id = int(payload.get("customer_id") or 0)
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(400, "请选择有效客户")
    currency = payload.get("currency") or customer.currency or "USD"
    payload.setdefault("currency", currency)
    payload.setdefault("exchange_rate", float(_rate(db, currency)))
    payload.setdefault("trade_terms", customer.trade_terms or "FOB")
    payload.setdefault("payment_terms_json", customer.payment_method_default or DEFAULT_TERMS)
    payload.setdefault("valid_until", date.today() + timedelta(days=10))
    payload.setdefault("owner_name", actor.name)
    payload.setdefault("quote_no", next_no(db, "QUOTATION"))
    payload.setdefault("seller_snapshot", {"name": get(db, "company_name")})
    payload.setdefault("buyer_snapshot", {"name": customer.name, "address": customer.address})
    q = Quotation(**{k: v for k, v in payload.items() if hasattr(Quotation, k)})
    q.created_by = actor.name
    db.add(q)
    db.flush()
    for idx, it in enumerate(items, 1):
        p = db.get(Product, int(it.get("product_id") or 0)) if it.get("product_id") else None
        unit_price = dec(it.get("unit_price") or (_price(db, p, customer_id, currency) if p else 0))
        qty = dec(it.get("qty") or 1)
        db.add(QuotationItem(quotation_id=q.id, line_no=idx, product_id=p.id if p else None,
                             oe_no=it.get("oe_no", ""), name_snapshot=it.get("name_snapshot", ""),
                             package_snapshot=it.get("package_snapshot", ""),
                             unit=it.get("unit", "PCS"), qty=qty, unit_price=unit_price,
                             amount=qty * unit_price,
                             cost_snapshot=dec(p.cost_price) if p else None,
                             match_status=it.get("match_status", "MATCHED"),
                             stock_status=it.get("stock_status", "OK"), created_by=actor.name))
    db.flush()
    rows = db.query(QuotationItem).filter_by(quotation_id=q.id).all()
    _recalc(q, rows)
    threshold = get_float(db, "discount_approve_pct", 5)
    if num(q.discount_pct) > threshold:
        q.status = "PENDING_APPROVAL"
        db.add(ApprovalRequest(flow_type="DISCOUNT", ref_type="quotation", ref_id=q.id,
                               ref_no=q.quote_no, amount=f"{num(q.discount_pct)}%",
                               requested_by=actor.name, status="PENDING", created_at=datetime.utcnow(),
                               payload={"total": float(q.total)}))
    audit(db, actor, "quotation.create", "quotations", q.id,
          detail=f"新建报价 {q.quote_no}，{len(rows)} 行")
    db.commit()
    return {"id": q.id, "quote_no": q.quote_no, "status": q.status,
            "total": float(q.total), "items": len(rows)}


@router.get("/quotations/{qid}")
def get_quotation(qid: int, actor: Actor = Depends(require("quotation", "view")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    data = as_dict(q, "quotation", actor)
    data["items"] = [row_dict(i, ["cost_snapshot"] if actor.role == "SALES" else [])
                     for i in db.query(QuotationItem).filter_by(quotation_id=qid).order_by(QuotationItem.line_no).all()]
    return data


@router.put("/quotations/{qid}")
def update_quotation(qid: int, body: dict, actor: Actor = Depends(require("quotation", "edit")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    if q.status == "CONVERTED":
        raise HTTPException(400, "已转订单的报价不可修改")
    items = body.pop("items", None)
    for k, v in body.items():
        if hasattr(Quotation, k) and k not in ("id", "quote_no", "created_at"):
            setattr(q, k, v)
    if items is not None:
        db.query(QuotationItem).filter_by(quotation_id=qid).delete()
        for idx, it in enumerate(items, 1):
            qty, price = dec(it.get("qty") or 1), dec(it.get("unit_price") or 0)
            db.add(QuotationItem(quotation_id=qid, line_no=idx,
                                 product_id=it.get("product_id"), oe_no=it.get("oe_no", ""),
                                 name_snapshot=it.get("name_snapshot", ""),
                                 package_snapshot=it.get("package_snapshot", ""),
                                 unit=it.get("unit", "PCS"), qty=qty, unit_price=price,
                                 amount=qty * price, cost_snapshot=it.get("cost_snapshot"),
                                 match_status=it.get("match_status", "MATCHED"), created_by=actor.name))
        q.version = (q.version or 1) + 1
    db.flush()
    _recalc(q, db.query(QuotationItem).filter_by(quotation_id=qid).all())
    audit(db, actor, "quotation.update", "quotations", qid, detail=f"修改报价 v{q.version}")
    db.commit()
    return {"message": "已保存", "version": q.version, "total": float(q.total)}


@router.delete("/quotations/{qid}")
def delete_quotation(qid: int, actor: Actor = Depends(require("quotation", "edit")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    q.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "已删除"}


@router.get("/quotations/{qid}/pdf")
def quotation_pdf(qid: int, _=Depends(require("quotation", "export")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    if q.status == "PENDING_APPROVAL":
        raise HTTPException(400, "折扣超阈值，需先审批通过才能发送/导出")
    bank = db.get(BankAccount, q.bank_account_id) if q.bank_account_id else db.query(BankAccount).filter_by(is_active=True).first()
    items = db.query(QuotationItem).filter_by(quotation_id=qid).order_by(QuotationItem.line_no).all()
    content = build_quotation_pdf(db, q, db.get(Customer, q.customer_id), items, bank)
    return pdf_response(content, f"{q.quote_no}.pdf")


@router.get("/quotations/{qid}/excel")
def quotation_excel(qid: int, _=Depends(require("quotation", "export")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    items = db.query(QuotationItem).filter_by(quotation_id=qid).order_by(QuotationItem.line_no).all()
    headers = ["#", "OE NO.", "PRODUCT NAME", "PACKAGE", "UNIT", "QTY", "UNIT PRICE", "AMOUNT"]
    rows = [[i.line_no, i.oe_no, i.name_snapshot, i.package_snapshot, i.unit,
             num(i.qty), num(i.unit_price), num(i.amount)] for i in items]
    rows.append(["", "", "", "", "", "", "TOTAL", num(q.total)])
    return xlsx_response(export_excel(headers, rows, q.quote_no), f"{q.quote_no}.xlsx")


class SendIn(BaseModel):
    channel: str = "EMAIL"


@router.post("/quotations/{qid}/send")
def send_quotation(qid: int, body: SendIn, actor: Actor = Depends(require("quotation", "edit")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    if q.status == "PENDING_APPROVAL":
        raise HTTPException(400, "折扣待审批，暂不能发送")
    q.sent_at = datetime.utcnow()
    q.sent_channel = body.channel
    q.status = "SENT"
    audit(db, actor, "quotation.send", "quotations", qid, detail=f"发送渠道 {body.channel}")
    db.commit()
    return {"message": "已记录发送打点", "sent_at": q.sent_at.isoformat()}


@router.post("/quotations/{qid}/convert")
def convert_to_order(qid: int, actor: Actor = Depends(require("order", "create")), db=Depends(get_db)):
    q = db.get(Quotation, qid)
    if not q:
        raise HTTPException(404, "报价单不存在")
    if q.status == "CONVERTED":
        raise HTTPException(400, "该报价已转订单")
    c = db.get(Customer, q.customer_id)
    terms = q.payment_terms_json or DEFAULT_TERMS
    deposit_pct = sum(num(t.get("pct")) for t in terms if "deposit" in str(t.get("label", "")).lower()) or 30
    collection = (c.payment_policy == "OLD_COLLECTION") if c else False
    order = SalesOrder(order_no=next_no(db, "ORDER"), quotation_id=q.id,
                       customer_id=q.customer_id, contact_id=q.contact_id,
                       owner_name=q.owner_name or actor.name, currency=q.currency,
                       exchange_rate=q.exchange_rate, trade_terms=q.trade_terms,
                       loading_port=q.loading_port, destination=q.destination,
                       payment_terms_json=terms, payment_method="COLLECTION" if collection else "TT",
                       subtotal=q.subtotal, discount=q.discount_amount, total=q.total,
                       deposit_amount=q.total * Decimal(str(deposit_pct)) / Decimal("100"),
                       balance_amount=q.total - q.total * Decimal(str(deposit_pct)) / Decimal("100"),
                       status="PREPARING" if collection else "PENDING_DEPOSIT",
                       delivery_date=date.today() + timedelta(days=int(num(q.delivery_days) or 45)),
                       due_date=date.today() + timedelta(days=int(c.payment_terms_days or 0) if c else 0),
                       source_channel=c.source_channel if c else None,
                       source_ref=c.source_ref if c else None, created_by=actor.name)
    db.add(order)
    db.flush()
    for i in db.query(QuotationItem).filter_by(quotation_id=qid).order_by(QuotationItem.line_no).all():
        db.add(SalesOrderItem(order_id=order.id, line_no=i.line_no, product_id=i.product_id,
                              oe_no=i.oe_no, name_snapshot=i.name_snapshot,
                              package_snapshot=i.package_snapshot, unit=i.unit, qty=i.qty,
                              unit_price=i.unit_price, amount=i.amount,
                              cost_snapshot=i.cost_snapshot, created_by=actor.name))
        if i.product_id:
            from ..services.stock import allocate
            try:
                allocate(db, product_id=i.product_id, warehouse_id=1, qty=i.qty, order_id=order.id)
            except HTTPException:
                pass  # 库存不足不阻断下单，报价行已标「需采购」
    q.status = "CONVERTED"
    audit(db, actor, "quotation.convert", "quotations", qid, detail=f"转订单 {order.order_no}")
    db.commit()
    return {"order_id": order.id, "order_no": order.order_no, "status": order.status}


@router.get("/quick-price")
def quick_price(oe: str = "", customer_id: int = 0, currency: str = "USD",
                _=Depends(require("quotation", "view")), db=Depends(get_db)):
    """F2 快速查价：型号秒查 → 可复制报价片段。"""
    p, status = _product_by_oe(db, normalize_oe(oe))
    if not p:
        raise HTTPException(404, "未找到该 OE 号对应产品")
    price = _price(db, p, customer_id, currency)
    primary = db.query(ProductOeNumber).filter_by(product_id=p.id, is_primary=True).first()
    snippet = f"{primary.oe_no if primary else oe} {p.name_en or p.name_cn} · {currency} {float(price):.2f} · WhatsApp"
    return {"product_id": p.id, "oe_no": primary.oe_no if primary else oe,
            "name": p.name_en or p.name_cn, "price": float(price), "currency": currency,
            "package": p.package_type, "match_status": status, "snippet": snippet}
