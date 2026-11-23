"""销售订单状态机：收款/出运自动驱动状态，人工只做例外；每次流转写日志。"""
from datetime import datetime

from fastapi import HTTPException

from ..core.utils import dec
from ..models.sales import OrderStatusLog, SalesOrder

FLOW = ["PENDING_DEPOSIT", "PREPARING", "PENDING_BALANCE", "READY_SHIP",
        "PARTIAL_SHIPPED", "SHIPPED", "COLLECTING", "CLOSED"]

ALLOWED = {
    "PENDING_DEPOSIT": {"PREPARING", "READY_SHIP", "CANCELLED", "PENDING_BALANCE"},
    "PREPARING": {"PENDING_BALANCE", "READY_SHIP", "CANCELLED"},
    "PENDING_BALANCE": {"READY_SHIP", "CANCELLED", "PREPARING"},
    "READY_SHIP": {"PARTIAL_SHIPPED", "SHIPPED", "CANCELLED"},
    "PARTIAL_SHIPPED": {"SHIPPED", "COLLECTING", "CANCELLED"},
    "SHIPPED": {"COLLECTING", "CLOSED", "CANCELLED"},
    "COLLECTING": {"CLOSED", "CANCELLED"},
    "CLOSED": set(), "CANCELLED": set(),
}


def transition(db, order: SalesOrder, to_status, actor=None, trigger="MANUAL", ref_id=None, note=None):
    if to_status == order.status:
        return order
    # 样品免收款：允许从任意未结案状态由 PAYMENT 触发器直接结案（业务特例）
    sample_close = (to_status == "CLOSED" and trigger == "PAYMENT"
                    and getattr(order, "sample_free", False))
    if to_status not in ALLOWED.get(order.status, set()) and not sample_close:
        raise HTTPException(400, f"状态不允许从 {order.status} 流转到 {to_status}")
    db.add(OrderStatusLog(created_at=datetime.utcnow(), order_id=order.id,
                          from_status=order.status, to_status=to_status, trigger=trigger,
                          ref_id=ref_id, operator_id=getattr(actor, "id", None),
                          operator_name=getattr(actor, "name", "system"), note=note))
    order.status = to_status
    db.flush()
    return order


def received_total(db, order_id):
    from ..models.finance import PaymentAllocation
    rows = db.query(PaymentAllocation).filter_by(target_type="ORDER", target_id=order_id).all()
    return sum(dec(r.amount) for r in rows)


def apply_receipt(db, order: SalesOrder, actor=None, payment_id=None):
    """收款核销后：定金到 → 备货中；全款到 → 待出运；样品免收款 → 结案。"""
    total = received_total(db, order.id)
    from decimal import Decimal
    total_amount = dec(order.total)
    if order.sample_free and order.status not in ("CLOSED", "CANCELLED"):
        return transition(db, order, "CLOSED", actor, "PAYMENT", payment_id, "样品免收款结案")
    if total >= total_amount > 0:
        if order.status == "PENDING_DEPOSIT":
            transition(db, order, "PREPARING", actor, "PAYMENT", payment_id, "定金到账")
        if order.status in ("PREPARING", "PENDING_BALANCE"):
            return transition(db, order, "READY_SHIP", actor, "PAYMENT", payment_id, "尾款收齐")
        return order
    if order.status == "PENDING_DEPOSIT" and total > 0:
        return transition(db, order, "PREPARING", actor, "PAYMENT", payment_id, "定金到账")
    return order


def apply_shipment(db, order: SalesOrder, actor=None, shipment_id=None, all_shipped=False):
    if order.status in ("CLOSED", "CANCELLED"):
        return order
    if order.status == "PENDING_BALANCE":
        # 状态机不允许「待尾款 → 部分出运」直跳，先推进到待出运，避免出运接口 400
        transition(db, order, "READY_SHIP", actor, "SHIPMENT", shipment_id, "部分出运前推进")
    if all_shipped and order.status in ("READY_SHIP", "PARTIAL_SHIPPED"):
        return transition(db, order, "SHIPPED", actor, "SHIPMENT", shipment_id, "全部出运")
    if order.status in ("READY_SHIP", "PARTIAL_SHIPPED", "PENDING_BALANCE"):
        return transition(db, order, "PARTIAL_SHIPPED", actor, "SHIPMENT", shipment_id, "部分出运")
    return order


def apply_collection(db, order: SalesOrder, actor=None, shipment_id=None):
    if order.status in ("SHIPPED", "PARTIAL_SHIPPED", "COLLECTING"):
        return transition(db, order, "COLLECTING", actor, "SHIPMENT", shipment_id, "货代代收中")
    return order
