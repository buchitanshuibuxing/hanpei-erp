"""自动催办：每小时检查报价回访 / 定金未收 / 代收超期，站内消息按天去重。"""
from datetime import date, datetime, timedelta

from ..core.audit import notify
from ..core.settings_service import get_float
from ..db import SessionLocal
from ..models.sales import Quotation, SalesOrder
from ..models.shipping import Shipment
from ..models.system import Notification


def _already(db, user_name, title):
    today = datetime.utcnow().date()
    return db.query(Notification).filter_by(user_name=user_name, title=title).filter(
        Notification.created_at >= datetime.combine(today, datetime.min.time())
    ).first() is not None


def check_reminders(manual=False):
    created = []
    with SessionLocal() as db:
        q_days = get_float(db, "remind_days_quote", 10)
        d_days = get_float(db, "remind_days_deposit", 3)
        c_days = get_float(db, "remind_days_collection", 7)
        cutoff_q = datetime.utcnow() - timedelta(days=q_days)
        for q in db.query(Quotation).filter_by(status="SENT").all():
            if q.sent_at and q.sent_at < cutoff_q:
                title = f"报价 {q.quote_no} 超期未回访"
                user = q.owner_name or "admin"
                if not _already(db, user, title):
                    notify(db, user, title, f"发送于 {q.sent_at:%Y-%m-%d}，请跟进客户确认", "quotation", q.id)
                    created.append(title)
        cutoff_d = datetime.utcnow() - timedelta(days=d_days)
        for o in db.query(SalesOrder).filter_by(status="PENDING_DEPOSIT").all():
            if o.created_at and o.created_at < cutoff_d:
                title = f"订单 {o.order_no} 定金未收"
                user = o.owner_name or "admin"
                if not _already(db, user, title):
                    notify(db, user, title, "PI 已发出但定金尚未到账，请催款", "order", o.id)
                    created.append(title)
        cutoff_c = date.today() - timedelta(days=c_days)
        for s in db.query(Shipment).filter_by(collection_flag=True).all():
            if s.eta and s.eta < cutoff_c:
                title = f"批次 {s.shipment_no} 代收回款超期"
                if not _already(db, "finance", title):
                    notify(db, "finance", title, "请联系货代核对代收台账", "shipment", s.id)
                    created.append(title)
        db.commit()
    return created
