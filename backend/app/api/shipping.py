"""出运跟单与单证：分批出运、分箱明细、拼柜建议、运费、国内 PL 导入 → 客户版装箱单。"""
import re
from datetime import datetime
from decimal import Decimal

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy import func

from ..core.audit import audit
from ..core.crud import create_resource, list_resource
from ..core.deps import Actor, check_parent_owner, require
from ..core.normalize import normalize_oe
from ..core.numbering import next_no
from ..core.utils import dec, num, row_dict
from ..db import get_db
from ..models.crm import Customer
from ..models.product import ProductOeNumber
from ..models.sales import SalesOrder, SalesOrderItem
from ..models.shipping import (Document, FreightCost, Shipment, ShipmentCarton,
                               ShipmentContainer, ShipmentItem)
from ..services import stock as stock_svc
from ..services.excel import read_excel
from ..services.order_state import apply_shipment
from ..services.pdf import build_packing_list_pdf
from .helpers import pdf_response, save_bytes

router = APIRouter(prefix="/api", tags=["出运与单证"])

CONTAINER_CAPACITY = {"20GP": 28.0, "40GP": 58.0, "40HQ": 68.0}  # CBM 近似可用容积


def _sync_shipped(db, order_id, shipment_id):
    """以 ShipmentItem 为唯一事实源重算订单行已出运数量，并卡住累计上限。

    create_shipment 与 pl-import 两条入口都走这里，避免「增量累加」被改单/重导入绕过。
    """
    lines = db.query(SalesOrderItem).filter_by(order_id=order_id).all()
    for line in lines:
        other = db.query(func.coalesce(func.sum(ShipmentItem.qty), 0)).filter(
            ShipmentItem.order_item_id == line.id,
            ShipmentItem.shipment_id != shipment_id).scalar() or 0
        mine = db.query(func.coalesce(func.sum(ShipmentItem.qty), 0)).filter(
            ShipmentItem.order_item_id == line.id,
            ShipmentItem.shipment_id == shipment_id).scalar() or 0
        total = dec(other) + dec(mine)
        if total > dec(line.qty) + Decimal("0.000001"):
            raise HTTPException(400, f"分批出运数量超过订单数量：行 {line.line_no} 上限 "
                                     f"{float(dec(line.qty))}，累计 {float(total)}")
        line.qty_shipped = total
    return lines


@router.get("/shipments")
def list_shipments(request: Request, actor: Actor = Depends(require("shipment", "view")), db=Depends(get_db)):
    return list_resource(db, Shipment, actor, "shipment", request,
                         like_fields=("shipment_no", "bl_no", "carrier"))


@router.post("/shipments")
def create_shipment(body: dict, actor: Actor = Depends(require("shipment", "create")), db=Depends(get_db)):
    payload = dict(body)
    items = payload.pop("items", [])
    order = db.get(SalesOrder, int(payload.get("order_id") or 0))
    if not order:
        raise HTTPException(400, "请选择有效订单")
    seq = db.query(Shipment).filter_by(order_id=order.id).count() + 1
    payload.setdefault("shipment_no", next_no(db, "SHIPMENT"))
    payload.setdefault("batch_seq", seq)
    payload.setdefault("status", "BOOKING")
    s = create_resource(db, Shipment, payload, actor, module="shipment")
    for it in items:
        qty = dec(it.get("qty") or 0)
        if qty <= 0:
            raise HTTPException(400, "出运数量必须大于 0")
        order_item_id = it.get("order_item_id")
        if order_item_id:
            oi = db.get(SalesOrderItem, int(order_item_id))
            if not oi or oi.order_id != order.id:
                raise HTTPException(400, f"订单明细不存在：{order_item_id}")
        db.add(ShipmentItem(shipment_id=s.id, order_item_id=order_item_id,
                            product_id=it.get("product_id"),
                            name_snapshot=it.get("name_snapshot", ""),
                            oe_no=it.get("oe_no", ""), qty=qty,
                            ctn_no=it.get("ctn_no", ""),
                            amount=dec(it.get("amount") or 0),
                            created_by=actor.name))
        # 闭环：出运扣减实物库存、同步释放下单时的占用量（两者同减，可用量保持一致）。
        # 未备足货时允许负库存并留流水，采购到货自动回正，绝不静默丢失出运记录。
        if it.get("product_id") and qty > 0:
            wh = 1  # 与 quotations.convert 的 allocate 默认仓库一致
            stock_svc.move(db, product_id=int(it["product_id"]), warehouse_id=wh, qty=qty,
                           move_type="OUT_SALE", ref_type="SHIPMENT", ref_id=s.id,
                           ref_no=s.shipment_no, operator=actor.name, allow_negative=True,
                           note="出运扣减；未备足货时形成欠货，采购到货回正")
            stock_svc.release(db, product_id=int(it["product_id"]), warehouse_id=wh, qty=qty)
    db.flush()
    left = _sync_shipped(db, order.id, s.id)
    all_shipped = bool(left) and all(dec(i.qty_shipped) >= dec(i.qty) for i in left)
    apply_shipment(db, order, actor, s.id, all_shipped=all_shipped)
    db.commit()
    return {"id": s.id, "shipment_no": s.shipment_no, "batch_seq": s.batch_seq,
            "order_status": order.status}


@router.get("/shipments/{sid}")
def get_shipment(sid: int, _=Depends(require("shipment", "view")), db=Depends(get_db)):
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    data = row_dict(s)
    data["items"] = [row_dict(i) for i in db.query(ShipmentItem).filter_by(shipment_id=sid).all()]
    data["cartons"] = [row_dict(i) for i in db.query(ShipmentCarton).filter_by(shipment_id=sid).all()]
    data["containers"] = [row_dict(i) for i in db.query(ShipmentContainer).filter_by(shipment_id=sid).all()]
    data["freight_costs"] = [row_dict(i) for i in db.query(FreightCost).filter_by(shipment_id=sid).all()]
    return data


class StatusIn(BaseModel):
    status: str


@router.post("/shipments/{sid}/status")
def shipment_status(sid: int, body: StatusIn, actor: Actor = Depends(require("shipment", "edit")), db=Depends(get_db)):
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    s.status = body.status
    audit(db, actor, "shipment.status", "shipments", sid, detail=f"推进到 {body.status}")
    db.commit()
    return {"status": s.status}


@router.post("/shipments/{sid}/cartons")
def add_carton(sid: int, body: dict, actor: Actor = Depends(require("shipment", "edit")), db=Depends(get_db)):
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    row = create_resource(db, ShipmentCarton, {**body, "shipment_id": sid}, actor)
    cartons = db.query(ShipmentCarton).filter_by(shipment_id=sid).all()
    s.total_ctn = len(cartons)
    s.total_cbm = sum(dec(num(c.length) * num(c.width) * num(c.height)) for c in cartons)
    s.total_weight = sum(dec(c.weight) for c in cartons)
    db.commit()
    return row_dict(row)


@router.post("/shipments/{sid}/freight-costs")
def add_freight(sid: int, body: dict, actor: Actor = Depends(require("shipment", "edit")), db=Depends(get_db)):
    check_parent_owner(db, actor, Shipment, sid, "出运批次")
    row = create_resource(db, FreightCost, {**body, "shipment_id": sid}, actor)
    db.commit()
    return row_dict(row)


@router.get("/shipments/{sid}/container-suggestion")
def container_suggestion(sid: int, _=Depends(require("shipment", "view")), db=Depends(get_db)):
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    cbm = num(s.total_cbm) or sum(num(num(c.length) * num(c.width) * num(c.height))
                                  for c in db.query(ShipmentCarton).filter_by(shipment_id=sid).all())
    suggestions = [{"type": k, "capacity_cbm": v, "usage_pct": round(cbm / v * 100, 1)}
                   for k, v in CONTAINER_CAPACITY.items()]
    best = next((x for x in suggestions if x["usage_pct"] <= 100), suggestions[-1])
    return {"total_cbm": cbm, "total_weight": num(s.total_weight),
            "suggestions": suggestions, "recommended": best}


@router.get("/shipments/{sid}/pl")
def packing_list_pdf(sid: int, _=Depends(require("document", "export")), db=Depends(get_db)):
    return _pl_response(db, sid)


def _pl_response(db, sid):
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    order = db.get(SalesOrder, s.order_id)
    customer = db.get(Customer, order.customer_id) if order else None
    items = db.query(ShipmentItem).filter_by(shipment_id=sid).all()
    cartons = db.query(ShipmentCarton).filter_by(shipment_id=sid).all()
    content = build_packing_list_pdf(db, s, order, customer, cartons, items)
    path = save_bytes(content, "packing_lists", f"{s.shipment_no}_PL.pdf")
    s.pl_file_path = path
    doc = db.query(Document).filter_by(shipment_id=sid, doc_type="PL").first()
    if doc is None:
        doc = Document(doc_type="PL", shipment_id=sid, order_id=s.order_id,
                       doc_no=s.shipment_no, created_at=datetime.utcnow())
        db.add(doc)
    doc.file_path, doc.status, doc.generated_at = path, "ISSUED", datetime.utcnow()
    db.commit()
    return pdf_response(content, f"{s.shipment_no}_PL.pdf")


@router.post("/shipments/{sid}/pl-import")
async def import_domestic_pl(sid: int, file: UploadFile = File(...),
                             actor: Actor = Depends(require("document", "create")), db=Depends(get_db)):
    """附录 B：国内装箱单导入 → 按 OE 带出英文品名与包装 → 生成客户版装箱单。"""
    s = db.get(Shipment, sid)
    if not s:
        raise HTTPException(404, "出运批次不存在")
    rows, _ = read_excel(await file.read())
    preview, unmatched = [], []
    order = db.get(SalesOrder, s.order_id) if s.order_id else None
    order_lines = db.query(SalesOrderItem).filter_by(order_id=s.order_id).all() if s.order_id else []

    def match_line(oe):
        n = normalize_oe(oe)
        return next((li for li in order_lines if normalize_oe(li.oe_no) == n), None)

    db.query(ShipmentItem).filter_by(shipment_id=sid).delete()
    db.query(ShipmentCarton).filter_by(shipment_id=sid).delete()
    db.flush()
    for idx, r in enumerate(rows, 2):
        oe = str(next((r[k] for k in ("OE", "OE号", "OE NO", "Part No") if k in r and r[k]), "") or "").strip()
        qty = num(next((r[k] for k in ("数量", "QTY", "Qty") if k in r and r[k]), 0))
        name_cn = str(next((r[k] for k in ("名称", "Part name", "品名") if k in r and r[k]), "") or "")
        ctn_no = str(next((r[k] for k in ("箱号", "CTN.", "CTN") if k in r and r[k]), "") or "")
        if not oe:
            continue
        if qty <= 0:
            raise HTTPException(400, f"装箱单第 {idx} 行数量必须大于 0")
        line = match_line(oe)
        hit = db.query(ProductOeNumber).filter_by(oe_norm=normalize_oe(oe)).first()
        name_en = ""
        if hit:
            from ..models.product import Product
            p = db.get(Product, hit.product_id)
            name_en = (p.name_en or p.name_cn) if p else ""
        if not name_en:
            unmatched.append(oe)
            name_en = name_cn
        db.add(ShipmentItem(shipment_id=sid, order_item_id=line.id if line else None,
                            product_id=hit.product_id if hit else None,
                            name_snapshot=name_en, oe_no=oe, qty=dec(qty), ctn_no=ctn_no,
                            amount=Decimal("0"), created_by=actor.name))
        preview.append({"oe": oe, "name_cn": name_cn, "name_en": name_en,
                        "qty": qty, "ctn_no": ctn_no, "matched": bool(hit),
                        "order_item_id": line.id if line else None})
        size = str(next((r[k] for k in ("SIZE(M)", "SIZE", "尺寸") if k in r and r[k]), "") or "")
        dims = re.findall(r"\d+\.?\d*", size)
        if ctn_no and len(dims) >= 3:
            db.add(ShipmentCarton(shipment_id=sid, ctn_no=ctn_no,
                                  length=dec(dims[0]), width=dec(dims[1]), height=dec(dims[2]),
                                  weight=dec(num(r.get("总重量") or 0)), created_by=actor.name))
    db.flush()
    # 单批数量上限 + 与手工出运共用同一累计越界校验，重导入不会绕过订单数量
    batch_total = sum(dec(i.qty) for i in
                      db.query(ShipmentItem).filter_by(shipment_id=sid).all())
    if order and order_lines:
        cap = sum(dec(li.qty) for li in order_lines)
        if batch_total > cap + Decimal("0.000001"):
            raise HTTPException(400, f"本批装箱数量 {float(batch_total)} 超过订单总量 {float(cap)}")
        _sync_shipped(db, order.id, sid)
    cartons = db.query(ShipmentCarton).filter_by(shipment_id=sid).all()
    s.total_ctn = len(cartons)
    s.total_cbm = sum(dec(num(c.length) * num(c.width) * num(c.height)) for c in cartons)
    s.total_weight = sum(dec(c.weight) for c in cartons)
    audit(db, actor, "pl.import", "shipments", sid, detail=f"导入 {len(preview)} 行，未匹配 {len(unmatched)}")
    db.commit()
    return {"preview": preview, "unmatched": unmatched,
            "total_ctn": s.total_ctn, "total_cbm": float(s.total_cbm or 0)}


# ---------------- 单证清单 ----------------
@router.get("/documents")
def list_documents(request: Request, actor: Actor = Depends(require("document", "view")), db=Depends(get_db)):
    return list_resource(db, Document, actor, "document", request, like_fields=("doc_no", "doc_type"))


@router.post("/documents")
def add_document(body: dict, actor: Actor = Depends(require("document", "create")), db=Depends(get_db)):
    row = create_resource(db, Document, body, actor,
                          defaults={"status": "TODO", "generated_at": datetime.utcnow()})
    db.commit()
    return row_dict(row)


@router.post("/documents/{did}/status")
def document_status(did: int, body: dict, actor: Actor = Depends(require("document", "edit")), db=Depends(get_db)):
    doc = db.get(Document, did)
    if not doc:
        raise HTTPException(404, "单证不存在")
    doc.status = body.get("status", "ISSUED")
    db.commit()
    return {"status": doc.status}
