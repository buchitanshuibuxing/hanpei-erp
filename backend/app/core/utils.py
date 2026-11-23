"""序列化、分页与通用响应工具。"""
from datetime import date, datetime
from decimal import Decimal


def num(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dec(value, default=0):
    if value is None or value == "":
        return Decimal(str(default))
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(str(default))


def _val(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


def row_dict(obj, mask_fields=None):
    """ORM 对象 → 可 JSON 序列化 dict；字段权限脱敏在此统一生效。"""
    if obj is None:
        return {}
    mask = set(mask_fields or [])
    out = {}
    for col in obj.__table__.columns:
        if col.name in mask:
            out[col.name] = None
            continue
        out[col.name] = _val(getattr(obj, col.name))
    return out


def paged(items, total, page, size):
    return {"items": items, "total": total, "page": page, "size": size,
            "pages": (total + size - 1) // size if size else 0}


def paginate(query, page=1, size=10):
    page = max(1, int(page or 1))
    size = max(1, min(100, int(size or 10)))
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    return rows, total, page, size


def ok(data=None, message="ok"):
    return {"code": 0, "message": message, "data": data}


def err(message, code=400):
    from fastapi import HTTPException
    raise HTTPException(status_code=code, detail=message)
