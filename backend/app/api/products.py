"""产品中心：档案/OE 号/分类/搜索/批量导入导出/图片按 OE 匹配/水印模板/发帖记录。"""
from datetime import datetime
from io import BytesIO

from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel

from ..core.crud import (as_dict, create_resource, delete_resource,
                         list_resource, update_resource)
from ..core.deps import Actor, check_parent_owner, require
from ..core.normalize import normalize_oe
from ..core.numbering import next_no
from ..core.utils import num, row_dict
from ..db import get_db
from ..models.product import (Category, Product, ProductAttachment,
                              ProductImage, ProductOeNumber, ProductRelation,
                              WatermarkTemplate)
from ..models.crm import SocialPost
from ..models.inventory import StockBalance
from ..services.excel import export_excel, read_excel
from .helpers import save_bytes, xlsx_response

router = APIRouter(prefix="/api", tags=["产品中心"])


def _sync_oes(db, product_id, oe_text, oe_type="OE"):
    """按归一化值去重挂 OE；返回一个 OE 可关联多个产品（交叉/替代关系）。"""
    from ..core.normalize import parse_oe_list
    added = 0
    for item in parse_oe_list(oe_text):
        exists = db.query(ProductOeNumber).filter_by(product_id=product_id,
                                                     oe_norm=item["norm"], oe_type=oe_type).first()
        if exists:
            continue
        db.add(ProductOeNumber(product_id=product_id, oe_no=item["raw"], oe_norm=item["norm"],
                               oe_type=oe_type,
                               is_primary=not db.query(ProductOeNumber).filter_by(
                                   product_id=product_id, is_primary=True).first()))
        added += 1
    db.flush()
    return added


@router.get("/products")
def list_products(request: Request, actor: Actor = Depends(require("product", "view")), db=Depends(get_db)):
    return list_resource(db, Product, actor, "product", request,
                         like_fields=("code", "name_cn", "name_en", "hs_code"))


@router.post("/products")
def create_product(body: dict, actor: Actor = Depends(require("product", "create")), db=Depends(get_db)):
    payload = dict(body)
    oes = payload.pop("oe_numbers", "") or payload.pop("oe_no", "")
    payload.setdefault("code", next_no(db, "PRODUCT"))
    row = create_resource(db, Product, payload, actor, module="product")
    if oes:
        _sync_oes(db, row.id, oes)
    db.commit()
    return as_dict(row, "product", actor)


@router.get("/products/export")
def export_products(actor: Actor = Depends(require("product", "export")), db=Depends(get_db)):
    rows = db.query(Product).filter(Product.deleted_at.is_(None)).all()
    headers = ["编码", "中文品名", "英文品名", "主OE", "HS编码", "标准价", "成本", "币种",
               "包装", "每箱数", "体积", "状态"]
    data = []
    for p in rows:
        oe = db.query(ProductOeNumber).filter_by(product_id=p.id, is_primary=True).first()
        data.append([p.code, p.name_cn, p.name_en, oe.oe_no if oe else "", p.hs_code,
                     num(p.standard_price), num(p.cost_price) if actor.role not in ("SALES",) else "",
                     p.currency, p.package_type, p.carton_qty, num(p.carton_volume), p.status])
    return xlsx_response(export_excel(headers, data, "产品目录"), "产品目录.xlsx")


@router.get("/products/template")
def product_template(_=Depends(require("product", "view"))):
    headers = ["编码", "中文品名", "英文品名", "OE号", "HS编码", "标准价", "成本",
               "币种", "包装", "内盒数", "每箱数", "单箱体积", "安全库存"]
    return xlsx_response(export_excel(headers, [], "导入模板"), "产品导入模板.xlsx")


@router.post("/products/import")
async def import_products(file: UploadFile = File(...),
                          actor: Actor = Depends(require("product", "create")), db=Depends(get_db)):
    rows, _ = read_excel(await file.read())
    created, skipped, errors = 0, 0, []
    for idx, r in enumerate(rows, 2):
        try:
            code = str(r.get("编码") or "").strip() or next_no(db, "PRODUCT")
            if db.query(Product).filter_by(code=code).first():
                skipped += 1
                continue
            p = Product(code=code, name_cn=str(r.get("中文品名") or ""),
                        name_en=str(r.get("英文品名") or ""),
                        hs_code=str(r.get("HS编码") or ""),
                        standard_price=num(r.get("标准价")), cost_price=num(r.get("成本")),
                        currency=str(r.get("币种") or "USD"),
                        package_type=str(r.get("包装") or ""),
                        inner_qty=int(num(r.get("内盒数"))), carton_qty=int(num(r.get("每箱数"))),
                        carton_volume=num(r.get("单箱体积")), safety_stock=int(num(r.get("安全库存"))),
                        status="ACTIVE", created_by=actor.name)
            db.add(p)
            db.flush()
            _sync_oes(db, p.id, str(r.get("OE号") or ""))
            created += 1
        except Exception as exc:
            errors.append(f"第 {idx} 行：{exc}")
    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


@router.get("/products/search")
def search_products(oe: str = "", keyword: str = "", customer_id: int = 0,
                    actor: Actor = Depends(require("product", "view")), db=Depends(get_db)):
    """OE 归一化秒查（快查价 / 报价行添加 / Ctrl+K 共用）。"""
    q = db.query(Product).filter(Product.deleted_at.is_(None))
    ids = None
    if oe:
        norm = normalize_oe(oe)
        ids = [r.product_id for r in db.query(ProductOeNumber).filter(
            ProductOeNumber.oe_norm.like(f"%{norm}%")).all()]
        if ids:
            q = q.filter(Product.id.in_(ids))
        else:
            q = q.filter(Product.name_en.ilike(f"%{norm}%"))
    if keyword:
        q = q.filter(Product.name_en.ilike(f"%{keyword}%") |
                     Product.name_cn.ilike(f"%{keyword}%") | Product.code.ilike(f"%{keyword}%"))
    out = []
    for p in q.limit(50).all():
        d = as_dict(p, "product", actor)
        d["oe_primary"] = ""
        oe_row = db.query(ProductOeNumber).filter_by(product_id=p.id, is_primary=True).first()
        if oe_row:
            d["oe_primary"] = oe_row.oe_no
        bal = db.query(StockBalance).filter_by(product_id=p.id).first()
        d["stock_qty"] = num(bal.qty) if bal else 0
        d["available_qty"] = (num(bal.qty) - num(bal.allocated_qty)) if bal else 0
        if customer_id:
            from ..models.crm import CustomerPriceItem
            cp = db.query(CustomerPriceItem).filter_by(customer_id=customer_id,
                                                       product_id=p.id).order_by(CustomerPriceItem.min_qty).first()
            if cp:
                d["agreement_price"] = num(cp.price)
        out.append(d)
    return out


@router.get("/products/{pid}")
def get_product(pid: int, actor: Actor = Depends(require("product", "view")), db=Depends(get_db)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "产品不存在")
    data = as_dict(p, "product", actor)
    data["oe_numbers"] = [row_dict(r) for r in db.query(ProductOeNumber).filter_by(product_id=pid).all()]
    data["images"] = [row_dict(r) for r in db.query(ProductImage).filter_by(product_id=pid).all()]
    data["attachments"] = [row_dict(r) for r in db.query(ProductAttachment).filter_by(product_id=pid).all()]
    data["relations"] = [row_dict(r) for r in db.query(ProductRelation).filter_by(product_id=pid).all()]
    return data


@router.put("/products/{pid}")
def update_product(pid: int, body: dict, actor: Actor = Depends(require("product", "edit")), db=Depends(get_db)):
    payload = dict(body)
    payload.pop("oe_numbers", None)
    update_resource(db, Product, pid, payload, actor, module="product")
    db.commit()
    return as_dict(db.get(Product, pid), "product", actor)


@router.delete("/products/{pid}")
def delete_product(pid: int, actor: Actor = Depends(require("product", "delete")), db=Depends(get_db)):
    delete_resource(db, Product, pid, actor, module="product")
    db.commit()
    return {"message": "已删除"}


class OeIn(BaseModel):
    oe_no: str
    oe_type: str = "OE"
    is_primary: bool = False


@router.post("/products/{pid}/oe-numbers")
def add_oe(pid: int, body: OeIn, actor: Actor = Depends(require("product", "edit")), db=Depends(get_db)):
    check_parent_owner(db, actor, Product, pid, "产品")
    n = normalize_oe(body.oe_no)
    if not n:
        raise HTTPException(400, "OE 号不能为空")
    if db.query(ProductOeNumber).filter_by(product_id=pid, oe_norm=n, oe_type=body.oe_type).first():
        raise HTTPException(400, "该 OE 号已存在")
    row = ProductOeNumber(product_id=pid, oe_no=body.oe_no, oe_norm=n, oe_type=body.oe_type,
                          is_primary=body.is_primary, created_by=actor.name)
    db.add(row)
    db.commit()
    return row_dict(row)


@router.delete("/products/oe-numbers/{oid}")
def delete_oe(oid: int, actor: Actor = Depends(require("product", "edit")), db=Depends(get_db)):
    row = db.get(ProductOeNumber, oid)
    if not row:
        raise HTTPException(404, "OE 号不存在")
    check_parent_owner(db, actor, Product, row.product_id, "产品")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.post("/products/images/match")
def match_images(body: dict, actor: Actor = Depends(require("product", "edit")), db=Depends(get_db)):
    """本地批量上传：文件名含 OE 号 → 自动挂到产品（未匹配返回待处理列表）。"""
    filenames = body.get("filenames", [])
    matched, pending = 0, []
    for fn in filenames:
        stem = str(fn).rsplit(".", 1)[0]
        norm = normalize_oe(stem)
        hit = db.query(ProductOeNumber).filter_by(oe_norm=norm).first()
        if not hit:
            hit = db.query(ProductOeNumber).filter(ProductOeNumber.oe_norm.like(f"%{norm}%")).first()
        if not hit or not norm:
            pending.append(fn)
            continue
        db.add(ProductImage(product_id=hit.product_id, source="LOCAL", filename=fn,
                            file_path=str(body.get("folder", "")) + "/" + fn,
                            is_main=False, created_by=actor.name))
        matched += 1
    db.commit()
    return {"matched": matched, "pending": pending}


@router.get("/categories")
def list_categories(request: Request, actor: Actor = Depends(require("product", "view")), db=Depends(get_db)):
    return list_resource(db, Category, actor, "product", request, like_fields=("name",))


@router.post("/categories")
def create_category(body: dict, actor: Actor = Depends(require("product", "create")), db=Depends(get_db)):
    row = create_resource(db, Category, body, actor)
    db.commit()
    return row_dict(row)


@router.get("/watermark-templates")
def list_watermarks(request: Request, actor: Actor = Depends(require("material", "view")), db=Depends(get_db)):
    return list_resource(db, WatermarkTemplate, actor, "material", request, like_fields=("name",))


@router.post("/watermark-templates")
def create_watermark(body: dict, actor: Actor = Depends(require("material", "create")), db=Depends(get_db)):
    row = create_resource(db, WatermarkTemplate, body, actor, defaults={"owner_name": actor.name})
    db.commit()
    return row_dict(row)


@router.put("/watermark-templates/{wid}")
def update_watermark(wid: int, body: dict, actor: Actor = Depends(require("material", "edit")), db=Depends(get_db)):
    update_resource(db, WatermarkTemplate, wid, body, actor, module="material")
    db.commit()
    return {"message": "已保存"}


@router.get("/social-posts")
def list_posts(request: Request, actor: Actor = Depends(require("material", "view")), db=Depends(get_db)):
    return list_resource(db, SocialPost, actor, "material", request, like_fields=("content",))


@router.post("/social-posts")
def create_post(body: dict, actor: Actor = Depends(require("material", "create")), db=Depends(get_db)):
    row = create_resource(db, SocialPost, body, actor,
                          defaults={"user_name": actor.name, "posted_at": datetime.utcnow()})
    db.commit()
    return row_dict(row)
