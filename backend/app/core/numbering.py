"""单据编号：sequences 驱动，按日归零，进程锁 + 版本号 CAS 防并发撞号。

并发策略（P0 补充）：
- 复用调用方事务（SQLite 单写者下若另开事务提交会与业务写锁互锁）；
- 进程内 threading.Lock + DB 层 version CAS 覆盖多进程；
- `reconcile_sequences()` 在启动时把序列与已有数据（含期初导入）对齐，避免撞号。
"""
import re
import threading
from datetime import datetime

from sqlalchemy import update

from ..db import SessionLocal
from ..models.system import Sequence

_LOCK = threading.Lock()
PREFIX = {
    "QUOTATION": ("QT", "%Y%m%d"), "ORDER": ("SO", "%Y%m%d"),
    "PURCHASE": ("PO", "%Y%m%d"), "SHIPMENT": ("SH", "%Y%m%d"),
    "PAYMENT": ("RC", "%Y%m%d"), "STOCKTAKE": ("PD", "%Y%m%d"),
    "PURCHASE_RETURN": ("TH", "%Y%m%d"), "CLAIM": ("CL", "%Y%m%d"),
    "CUSTOMER": ("C", ""), "PRODUCT": ("HP", ""), "LEAD": ("LD", ""),
}


def next_no(db=None, doc_type: str = "") -> str:
    key = doc_type.upper()
    prefix, pattern = PREFIX.get(key, (key[:2].upper(), "%Y%m%d"))
    stamp = datetime.utcnow().strftime(pattern) if pattern else ""
    today = datetime.utcnow().strftime("%Y%m%d")
    own_session = db is None
    s = db if db is not None else SessionLocal()
    with _LOCK:
        try:
            for _ in range(8):
                seq = s.query(Sequence).filter_by(doc_type=key).first()
                if seq is None:
                    s.add(Sequence(doc_type=key, prefix=prefix, date_pattern=pattern,
                                   current_date=today, next_no=1, created_at=datetime.utcnow()))
                    s.flush()
                    continue
                old_version = seq.version or 0
                if seq.current_date != today:
                    new_next, new_date = 1, today
                else:
                    new_next, new_date = (seq.next_no or 1), seq.current_date
                number = f"{seq.prefix}{stamp}{new_next:04d}"
                res = s.execute(
                    update(Sequence)
                    .where(Sequence.doc_type == key, Sequence.version == old_version)
                    .values(next_no=new_next + 1, current_date=new_date,
                            version=old_version + 1, updated_at=datetime.utcnow())
                )
                if res.rowcount == 1:
                    s.expire(seq)
                    if own_session:
                        s.commit()
                    return number
                s.expire_all()
            raise RuntimeError(f"单据编号 {key} 并发冲突，请重试")
        finally:
            if own_session:
                s.close()


def reconcile_sequences(db=None):
    """启动时把无日期前缀的编号序列与已有数据对齐（期初导入后不撞号）。"""
    from ..models.crm import Customer, Lead
    from ..models.product import Product

    own_session = db is None
    s = db if db is not None else SessionLocal()
    targets = [("CUSTOMER", Customer, "C"), ("PRODUCT", Product, "HP"), ("LEAD", Lead, "LD")]
    try:
        for doc_type, model, prefix in targets:
            if not hasattr(model, "code"):
                continue  # 线索等无编码字段的表不参与校准
            codes = [r[0] for r in s.query(model.code).all() if r[0]]
            nums = []
            for code in codes:
                if not str(code).startswith(prefix):
                    continue
                digits = re.sub(r"\D", "", str(code))
                if digits:
                    nums.append(int(digits))
            floor = max(nums) + 1 if nums else 1
            seq = s.query(Sequence).filter_by(doc_type=doc_type).first()
            if seq is None:
                p, pattern = PREFIX[doc_type]
                s.add(Sequence(doc_type=doc_type, prefix=p, date_pattern=pattern,
                               next_no=floor, created_at=datetime.utcnow()))
            elif (seq.next_no or 1) < floor:
                seq.next_no = floor
                seq.version = (seq.version or 0) + 1
        if own_session:
            s.commit()
    finally:
        if own_session:
            s.close()
