"""操作审计：关键写操作统一入口（密钥值不落日志）。"""
from datetime import datetime


def audit(db, user, action, ref_type=None, ref_id=None, detail="", before=None, after=None, ip=None):
    from ..models.system import AuditLog
    name = getattr(user, "name", None) or getattr(user, "username", None) or "system"
    db.add(AuditLog(
        created_at=datetime.utcnow(), user_name=name, action=action,
        ref_type=ref_type, ref_id=ref_id, detail=detail,
        before_json=before, after_json=after, ip=ip,
    ))


def notify(db, user_name, title, content, ref_type=None, ref_id=None, channel="SITE"):
    from ..models.system import Notification
    db.add(Notification(created_at=datetime.utcnow(), user_name=user_name,
                        title=title, content=content, ref_type=ref_type,
                        ref_id=ref_id, channel=channel))
