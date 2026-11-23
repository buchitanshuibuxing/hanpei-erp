"""通用 CRUD 骨架：列表分页/过滤/软删/字段脱敏/审计，减少重复代码。"""
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import or_

from .audit import audit
from .deps import visible
from .permissions import masked_fields
from .utils import paginate, paged, row_dict

SKIP_FIELDS = {"id", "created_at", "updated_at", "created_by", "updated_by"}


def _columns(model):
    return {c.name for c in model.__table__.columns}


def list_resource(db, model, actor, module, request: Request, like_fields=(), extra=None,
                  order_desc=True, mask=True):
    params = dict(request.query_params)
    page = int(params.pop("page", 1) or 1)
    size = int(params.pop("size", 10) or 10)
    keyword = params.pop("keyword", None)
    cols = _columns(model)
    q = visible(db.query(model), model, actor)
    if "deleted_at" in cols:
        q = q.filter(model.deleted_at.is_(None))
    for key, value in params.items():
        if key in cols and value not in (None, ""):
            q = q.filter(getattr(model, key) == value)
    if keyword and like_fields:
        conds = [getattr(model, f).ilike(f"%{keyword}%") for f in like_fields if f in cols]
        if conds:
            q = q.filter(or_(*conds))
    if extra is not None:
        q = extra(q)
    pk = "id" if "id" in cols else list(cols)[0]
    q = q.order_by(getattr(model, pk).desc() if order_desc else getattr(model, pk).asc())
    rows, total, page, size = paginate(q, page, size)
    hidden = masked_fields(actor.role, module) if mask else []
    return paged([row_dict(r, hidden) for r in rows], total, page, size)


def get_row(db, model, row_id, actor=None, name="记录"):
    row = db.get(model, int(row_id))
    if row is None:
        raise HTTPException(404, f"{name}不存在")
    if actor and actor.role == "SALES" and hasattr(model, "owner_name"):
        if getattr(row, "owner_name", None) not in (None, "", actor.name):
            raise HTTPException(404, f"{name}不存在")
    return row


def create_resource(db, model, payload, actor=None, defaults=None, module=None):
    cols = _columns(model)
    data = {k: v for k, v in (payload or {}).items()
            if k in cols and k not in SKIP_FIELDS and v is not None}
    for k, v in (defaults or {}).items():
        data.setdefault(k, v)
    row = model(**data)
    if "created_by" in cols and actor:
        row.created_by = actor.name
    db.add(row)
    db.flush()
    if module and actor:
        audit(db, actor, f"{module}.create", model.__tablename__, row.id,
              detail=f"新增 {model.__tablename__} #{row.id}")
    return row


def update_resource(db, model, row_id, payload, actor=None, module=None, immutable=()):
    cols = _columns(model)
    row = get_row(db, model, row_id, actor)
    before = row_dict(row)
    for k, v in (payload or {}).items():
        if k in cols and k not in SKIP_FIELDS and k not in immutable:
            setattr(row, k, v)
    if "updated_at" in cols:
        row.updated_at = datetime.utcnow()
    if "updated_by" in cols and actor:
        row.updated_by = actor.name
    db.flush()
    if module and actor:
        audit(db, actor, f"{module}.update", model.__tablename__, row.id,
              detail=f"修改 {model.__tablename__} #{row.id}", before=before, after=row_dict(row))
    return row


def delete_resource(db, model, row_id, actor=None, module=None):
    row = get_row(db, model, row_id, actor)
    if hasattr(model, "deleted_at"):
        row.deleted_at = datetime.utcnow()
    else:
        db.delete(row)
    db.flush()
    if module and actor:
        audit(db, actor, f"{module}.delete", model.__tablename__, int(row_id),
              detail=f"删除 {model.__tablename__} #{row_id}")
    return True


def as_dict(row, module, actor):
    return row_dict(row, masked_fields(actor.role, module))
