"""健康检查、全局搜索（Ctrl+K）、元数据字典、统一附件。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.deps import Actor, current_user
from ..core.normalize import normalize_oe
from ..core.utils import num, row_dict
from ..db import IS_SQLITE, get_db
from ..models.crm import Customer, Lead
from ..models.product import Product, ProductOeNumber
from ..models.sales import Quotation, SalesOrder
from ..models.system import Attachment
from ..services.order_state import FLOW as ORDER_FLOW

router = APIRouter(prefix="/api", tags=["公共"])


@router.get("/health")
def health():
    return {"status": "ok", "database": "sqlite" if IS_SQLITE else "postgresql",
            "version": "1.0.0", "service": "Hanpei ERP"}


@router.get("/meta")
def meta(_=Depends(current_user)):
    return {
        "order_status": ORDER_FLOW,
        "quotation_status": ["DRAFT", "PENDING_APPROVAL", "SENT", "CONFIRMED",
                             "REJECTED", "EXPIRED", "CONVERTED"],
        "shipment_status": ["BOOKING", "LOADED", "CLEARED", "DEPARTED", "ARRIVED", "RECEIVED"],
        "purchase_status": ["DRAFT", "APPROVED", "ORDERED", "PARTIAL_RECEIVED",
                            "RECEIVED", "CLOSED", "CANCELLED"],
        "currencies": ["USD", "SAR", "AED", "CNY", "EUR"],
        "trade_terms": ["FOB", "CIF", "CFR", "EXW", "DDP"],
        "doc_types": ["PI", "CI", "PL", "CONTRACT", "CUSTOMS", "BL", "CO", "CERT"],
        "move_types": ["IN_PURCHASE", "OUT_SALE", "IN_RETURN", "OUT_RETURN",
                       "TRANSFER", "SAMPLE", "ADJUST"],
    }


@router.get("/search")
def global_search(q: str = "", _=Depends(current_user), db=Depends(get_db)):
    if not q:
        return []
    out = []
    norm = normalize_oe(q)
    for oe in db.query(ProductOeNumber).filter(ProductOeNumber.oe_norm.like(f"%{norm}%")).limit(8).all():
        p = db.get(Product, oe.product_id)
        if p:
            out.append({"type": "product", "id": p.id, "title": f"{oe.oe_no} {p.name_en or p.name_cn}",
                        "url": f"/products?id={p.id}"})
    for c in db.query(Customer).filter(Customer.name.ilike(f"%{q}%")).limit(5).all():
        out.append({"type": "customer", "id": c.id, "title": c.name, "url": f"/customers?id={c.id}"})
    for x in db.query(Quotation).filter(Quotation.quote_no.ilike(f"%{q}%")).limit(5).all():
        out.append({"type": "quotation", "id": x.id, "title": f"{x.quote_no} · {num(x.total):,.2f} {x.currency}",
                    "url": f"/quotations?id={x.id}"})
    for x in db.query(SalesOrder).filter(SalesOrder.order_no.ilike(f"%{q}%")).limit(5).all():
        out.append({"type": "order", "id": x.id, "title": f"{x.order_no} · {x.status}",
                    "url": f"/orders?id={x.id}"})
    for x in db.query(Lead).filter(Lead.company.ilike(f"%{q}%")).limit(5).all():
        out.append({"type": "lead", "id": x.id, "title": x.company or x.contact_name or "线索",
                    "url": f"/leads?id={x.id}"})
    return out


@router.get("/attachments")
def attachments(request: Request, _=Depends(current_user), db=Depends(get_db)):
    ref_type = request.query_params.get("ref_type")
    ref_id = request.query_params.get("ref_id")
    q = db.query(Attachment)
    if ref_type:
        q = q.filter_by(ref_type=ref_type)
    if ref_id:
        q = q.filter_by(ref_id=int(ref_id))
    return [row_dict(a) for a in q.order_by(Attachment.id.desc()).limit(100).all()]
