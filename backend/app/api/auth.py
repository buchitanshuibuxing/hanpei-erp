"""认证：内部登录 / 门户登录 / 权限矩阵 / 密码修改；登录失败锁定对内外同时生效。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.audit import audit
from ..core.deps import current_user
from ..core.permissions import MODULES, ROLES, matrix
from ..core.security import (hash_password, is_locked, lock_until, make_token,
                             verify_password)
from ..db import get_db
from ..models.extended import PortalAccount
from ..models.system import LoginAttempt, User

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str
    password: str


def _attempt(db, username, ip, success, scope):
    db.add(LoginAttempt(created_at=datetime.utcnow(), username=username, ip=ip,
                        success=success, scope=scope))


def _internal_login(db, body: LoginIn, request: Request):
    ip = request.client.host if request.client else ""
    user = db.query(User).filter_by(username=body.username).first()
    if is_locked(getattr(user, "locked_until", None)):
        _attempt(db, body.username, ip, False, "INTERNAL")
        raise HTTPException(423, "账号已被临时锁定，请 15 分钟后重试或联系管理员")
    if not user or user.status != "ACTIVE" or not verify_password(body.password, user.password_hash):
        if user:
            user.failed_count = (user.failed_count or 0) + 1
            if user.failed_count >= 5:
                user.locked_until = lock_until(15)
                user.failed_count = 0
            db.commit()
        _attempt(db, body.username, ip, False, "INTERNAL")
        db.commit()
        raise HTTPException(401, "账号或密码错误")
    user.failed_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    _attempt(db, body.username, ip, True, "INTERNAL")
    audit(db, user, "login", "users", user.id, detail="内部登录")
    db.commit()
    token = make_token({"sub": user.username, "name": user.name,
                        "role": user.role_code, "scope": "internal"}, 30)
    return {"token": token, "scope": "internal",
            "user": {"id": user.id, "username": user.username, "name": user.name,
                     "role": user.role_code, "role_name": ROLES.get(user.role_code, ""),
                     "permissions": matrix().get(user.role_code, {})}}


@router.post("/login")
def login(body: LoginIn, request: Request, db=Depends(get_db)):
    return _internal_login(db, body, request)


@router.post("/portal/login", tags=["客户门户"])
def portal_login(body: LoginIn, request: Request, db=Depends(get_db)):
    ip = request.client.host if request.client else ""
    acc = db.query(PortalAccount).filter_by(username=body.username).first()
    if is_locked(getattr(acc, "locked_until", None)):
        raise HTTPException(423, "账号已被临时锁定，请稍后重试")
    if not acc or not acc.is_active or not verify_password(body.password, acc.password_hash):
        if acc:
            acc.failed_count = (acc.failed_count or 0) + 1
            if acc.failed_count >= 5:
                acc.locked_until = lock_until(15)
                acc.failed_count = 0
            db.commit()
        _attempt(db, body.username, ip, False, "PORTAL")
        db.commit()
        raise HTTPException(401, "账号或密码错误")
    acc.failed_count, acc.locked_until = 0, None
    acc.last_login_at = datetime.utcnow()
    _attempt(db, body.username, ip, True, "PORTAL")
    db.commit()
    token = make_token({"sub": acc.username, "name": acc.username,
                        "scope": "portal", "cid": acc.customer_id}, 7)
    return {"token": token, "scope": "portal", "customer_id": acc.customer_id,
            "user": {"username": acc.username, "name": acc.username, "role": "PORTAL"}}


@router.get("/me")
def me(actor=Depends(current_user)):
    return {"username": actor.username, "name": actor.name, "role": actor.role,
            "role_name": ROLES.get(actor.role, ""), "scope": actor.scope,
            "permissions": matrix().get(actor.role, {})}


@router.get("/matrix")
def permission_matrix(_=Depends(current_user)):
    return {"roles": ROLES, "modules": MODULES, "matrix": matrix()}


class PwdIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: PwdIn, actor=Depends(current_user), db=Depends(get_db)):
    user = db.query(User).filter_by(username=actor.username).first()
    if not user or not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "原密码不正确")
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    user.password_hash = hash_password(body.new_password)
    audit(db, actor, "password.change", "users", user.id, detail="修改密码")
    db.commit()
    return {"message": "密码已修改"}


@router.post("/logout")
def logout(actor=Depends(current_user), db=Depends(get_db)):
    audit(db, actor, "logout", "users", actor.id, detail="退出登录")
    db.commit()
    return {"message": "已退出"}
