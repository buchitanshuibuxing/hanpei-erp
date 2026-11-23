"""依赖注入：当前用户、权限校验、数据隔离与字段脱敏。"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from ..db import get_db
from ..models.system import User
from .permissions import can, masked_fields
from .security import parse_token


@dataclass
class Actor:
    id: int = 0
    username: str = ""
    name: str = ""
    role: str = "SALES"
    scope: str = "internal"
    customer_id: int = 0


def _from_payload(request: Request, db, expected_scope):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    payload = parse_token(token)
    if not payload:
        raise HTTPException(401, "登录已失效，请重新登录")
    scope = payload.get("scope", "internal")
    if scope != expected_scope:
        raise HTTPException(403, "令牌权限范围不匹配：此接口不接受该类型账号")
    if expected_scope == "internal":
        user = db.query(User).filter_by(username=payload.get("sub"), status="ACTIVE").first()
        if not user:
            raise HTTPException(401, "账号不存在或已停用")
        return Actor(id=user.id, username=user.username, name=user.name,
                     role=user.role_code or "SALES", scope="internal")
    return Actor(id=payload.get("cid", 0), username=payload.get("sub", ""),
                 name=payload.get("name", ""), role="PORTAL", scope="portal",
                 customer_id=payload.get("cid", 0))


def current_user(request: Request, db=Depends(get_db)) -> Actor:
    return _from_payload(request, db, "internal")


def portal_actor(request: Request, db=Depends(get_db)) -> Actor:
    return _from_payload(request, db, "portal")


def require(module: str, action: str = "view"):
    def _dep(actor: Actor = Depends(current_user)):
        if not can(actor.role, module, action):
            raise HTTPException(403, f"无权限执行：{module}.{action}（角色 {actor.role}）")
        return actor
    return _dep


def visible(query, model, actor: Actor):
    """业务员只见 owner_name == 本人 的数据；管理员/财务/主管全量。"""
    if actor.role == "SALES" and hasattr(model, "owner_name"):
        return query.filter(model.owner_name == actor.name)
    return query


def mask(module: str, actor: Actor):
    return masked_fields(actor.role, module)


def check_owner(row, actor: Actor):
    if actor.role == "SALES" and getattr(row, "owner_name", None) not in (None, "", actor.name):
        raise HTTPException(404, "单据不存在")
