"""系统管理：用户/角色/参数/操作日志/通知/功能开关/备份/编号规则。"""
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core import settings_service
from ..core.audit import audit
from ..core.crud import create_resource, list_resource, update_resource
from ..core.deps import Actor, current_user, require
from ..core.security import hash_password
from ..core.utils import row_dict
from ..db import IS_SQLITE, ROOT, get_db
from ..models.system import (AuditLog, FeatureFlag, LoginAttempt, Notification,
                             Role, RolePermission, Sequence, Setting, User)
from .helpers import download

router = APIRouter(prefix="/api/system", tags=["系统管理"])
BACKUP_DIR = ROOT / "data" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/users")
def users(request: Request, actor: Actor = Depends(require("system", "view")), db=Depends(get_db)):
    data = list_resource(db, User, actor, "system", request, like_fields=("username", "name"))
    for r in data["items"]:
        r.pop("password_hash", None)
        r.pop("locked_until", None)
    return data


@router.post("/users")
def add_user(body: dict, actor: Actor = Depends(require("system", "create")), db=Depends(get_db)):
    payload = dict(body)
    pwd = payload.pop("password", "123456")
    if db.query(User).filter_by(username=payload.get("username")).first():
        raise HTTPException(400, "用户名已存在")
    payload["password_hash"] = hash_password(str(pwd))
    row = create_resource(db, User, payload, actor, module="system")
    db.commit()
    return {"id": row.id, "username": row.username}


@router.put("/users/{uid}")
def update_user(uid: int, body: dict, actor: Actor = Depends(require("system", "edit")), db=Depends(get_db)):
    payload = dict(body)
    pwd = payload.pop("password", None)
    if pwd:
        payload["password_hash"] = hash_password(str(pwd))
    update_resource(db, User, uid, payload, actor, module="system")
    audit(db, actor, "user.change", "users", uid, detail="修改用户/重置密码")
    db.commit()
    return {"message": "已保存"}


@router.delete("/users/{uid}")
def disable_user(uid: int, actor: Actor = Depends(require("system", "edit")), db=Depends(get_db)):
    update_resource(db, User, uid, {"status": "DISABLED"}, actor, module="system")
    db.commit()
    return {"message": "已停用"}


@router.get("/roles")
def roles(_=Depends(require("system", "view")), db=Depends(get_db)):
    return [row_dict(r) for r in db.query(Role).all()]


@router.get("/role-permissions")
def role_permissions(request: Request, actor: Actor = Depends(require("system", "view")), db=Depends(get_db)):
    return list_resource(db, RolePermission, actor, "system", request)


@router.get("/settings")
def list_settings(_=Depends(require("system", "view")), db=Depends(get_db)):
    return settings_service.listing(db)


@router.put("/settings")
def save_settings(body: dict, actor: Actor = Depends(require("system", "edit")), db=Depends(get_db)):
    changed = []
    for key, value in body.items():
        if key in settings_service.SECRET_KEYS and value == "******":
            continue  # 前端回传掩码，保持原值
        settings_service.set_value(db, key, value, actor.name)
        changed.append(key)
    audit(db, actor, "settings.change", "settings", None, detail="修改参数：" + ", ".join(changed))
    db.commit()
    return {"changed": changed}


@router.get("/audit-logs")
def audit_logs(request: Request, actor: Actor = Depends(require("system", "view")), db=Depends(get_db)):
    return list_resource(db, AuditLog, actor, "system", request, like_fields=("action", "user_name"))


@router.get("/login-attempts")
def login_attempts(request: Request, actor: Actor = Depends(require("system", "view")), db=Depends(get_db)):
    return list_resource(db, LoginAttempt, actor, "system", request, like_fields=("username",))


@router.get("/notifications")
def notifications(request: Request, actor: Actor = Depends(current_user), db=Depends(get_db)):
    return list_resource(db, Notification, actor, "system", request,
                         extra=lambda q: q.filter(Notification.user_name.in_([actor.name, "ALL"])))


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, actor: Actor = Depends(current_user), db=Depends(get_db)):
    row = db.get(Notification, nid)
    if row:
        row.is_read = True
        db.commit()
    return {"message": "已读"}


@router.get("/feature-flags")
def feature_flags(_=Depends(require("system", "view")), db=Depends(get_db)):
    return [row_dict(f) for f in db.query(FeatureFlag).order_by(FeatureFlag.code).all()]


@router.put("/feature-flags/{code}")
def set_feature_flag(code: str, body: dict, actor: Actor = Depends(require("system", "edit")), db=Depends(get_db)):
    f = db.query(FeatureFlag).filter_by(code=code).first()
    if not f:
        raise HTTPException(404, "开关不存在")
    f.enabled = bool(body.get("enabled"))
    audit(db, actor, "feature.toggle", "feature_flags", f.id, detail=f"{code} = {f.enabled}")
    db.commit()
    return {"code": code, "enabled": f.enabled}


@router.get("/sequences")
def sequences(_=Depends(require("system", "view")), db=Depends(get_db)):
    return [row_dict(s) for s in db.query(Sequence).order_by(Sequence.doc_type).all()]


@router.post("/backup")
def create_backup(actor: Actor = Depends(require("system", "edit")), db=Depends(get_db)):
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if IS_SQLITE:
        src = ROOT / "data" / "erp.db"
        dst = BACKUP_DIR / f"erp_{stamp}.db"
        shutil.copy2(src, dst)
        size = dst.stat().st_size
    else:
        raise HTTPException(400, "PostgreSQL 请使用 deploy/backup.sh（pg_dump）")
    audit(db, actor, "backup.create", "system", None, detail=f"{dst.name} ({size} bytes)")
    db.commit()
    return {"file": dst.name, "size": size, "created_at": stamp}


@router.get("/backups")
def list_backups(_=Depends(require("system", "view"))):
    return [{"file": p.name, "size": p.stat().st_size,
             "created_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
            for p in sorted(BACKUP_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)]


@router.get("/backups/{name}")
def download_backup(name: str, _=Depends(require("system", "view"))):
    path = BACKUP_DIR / Path(name).name
    if not path.exists():
        raise HTTPException(404, "备份文件不存在")
    return download(path.read_bytes(), name, "application/octet-stream")
