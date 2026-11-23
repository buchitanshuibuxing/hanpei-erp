"""报表与驾驶舱：全部从真实单据聚合，标注统计口径。"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request

from ..core.crud import list_resource
from ..core.deps import Actor, require
from ..core.settings_service import get_float
from ..core.utils import num, paged
from ..db import get_db
from ..models.crm import Customer, Lead
from ..models.finance import Commission, OrderProfit, Payment, PaymentAllocation
from ..models.inventory import StockBalance, StockMove
from ..models.product import Product
from ..models.sales import Quotation, SalesOrder, SalesOrderItem

router = APIRouter(prefix="/api/reports", tags=["报表看板"])


def _month(d):
    return (d or datetime.utcnow()).strftime("%Y-%m") if isinstance(d, datetime) else str(d or "")[:7]


@router.get("/dashboard")
def dashboard(actor: Actor = Depends(require("report", "view")), db=Depends(get_db)):
    """口径：近 30 天滚动；金额按订单原币汇总（不跨币种折算）。"""
    since = datetime.utcnow() - timedelta(days=30)
    orders = db.query(SalesOrder).filter(SalesOrder.created_at >= since).all() if SalesOrder.created_at is not None else []
    revenue = sum(num(o.total) for o in orders)
    received = sum(num(a.amount) for a in db.query(PaymentAllocation).filter(
        PaymentAllocation.created_at >= since).all())
    profit = sum(num(p.net_profit) for p in db.query(OrderProfit).all())
    target = get_float(db, "sales_target", 0)
    low_stock = []
    for b in db.query(StockBalance).all():
        p = db.get(Product, b.product_id)
        if p and num(b.qty) < num(p.safety_stock):
            low_stock.append({"code": p.code, "name": p.name_en or p.name_cn,
                              "qty": num(b.qty), "safety": num(p.safety_stock)})
    overdue = [{"order_no": o.order_no, "delivery_date": str(o.delivery_date or "")}
               for o in db.query(SalesOrder).filter(
                   SalesOrder.status.notin_(["CLOSED", "CANCELLED", "SHIPPED"])).all()
               if o.delivery_date and o.delivery_date < date.today()]
    pending = db.query(SalesOrder).filter(SalesOrder.status.notin_(["CLOSED", "CANCELLED"])).count()
    return {"scope": "近 30 天滚动 / 金额按原币汇总",
            "kpi": {"order_count_30d": len(orders), "revenue_30d": revenue,
                    "received_30d": received, "net_profit_all": profit,
                    "open_orders": pending, "sales_target": target,
                    "target_progress": round(received / target * 100, 1) if target else 0,
                    "low_stock_count": len(low_stock), "overdue_count": len(overdue)},
            "low_stock": low_stock[:10], "overdue_orders": overdue[:10],
            "status_breakdown": _status_breakdown(db)}


def _status_breakdown(db):
    d = defaultdict(int)
    for o in db.query(SalesOrder).all():
        d[o.status] += 1
    return dict(d)


@router.get("/sales")
def sales_report(months: int = 6, _=Depends(require("report", "view")), db=Depends(get_db)):
    buckets = defaultdict(lambda: {"orders": 0, "amount": 0.0, "received": 0.0})
    for o in db.query(SalesOrder).all():
        m = _month(o.created_at)
        buckets[m]["orders"] += 1
        buckets[m]["amount"] += num(o.total)
    for a in db.query(PaymentAllocation).all():
        buckets[_month(a.created_at)]["received"] += num(a.amount)
    keys = sorted(buckets.keys(), reverse=True)[:months]
    return [{"month": k, **buckets[k]} for k in reversed(keys)]


@router.get("/products")
def product_report(_=Depends(require("report", "view")), db=Depends(get_db)):
    agg = defaultdict(lambda: {"qty": 0.0, "amount": 0.0, "orders": 0})
    for i in db.query(SalesOrderItem).all():
        row = agg[i.product_id or 0]
        row["qty"] += num(i.qty)
        row["amount"] += num(i.amount)
        row["orders"] += 1
    rows = []
    for pid, v in agg.items():
        p = db.get(Product, pid) if pid else None
        rows.append({"product_id": pid, "code": p.code if p else "", "name": (p.name_en or p.name_cn) if p else "",
                     **v})
    return sorted(rows, key=lambda x: x["amount"], reverse=True)[:20]


@router.get("/channels")
def channel_report(_=Depends(require("report", "view")), db=Depends(get_db)):
    agg = defaultdict(lambda: {"leads": 0, "customers": 0, "orders": 0, "amount": 0.0})
    for l in db.query(Lead).all():
        agg[l.channel or "UNKNOWN"]["leads"] += 1
    for c in db.query(Customer).all():
        agg[c.source_channel or "UNKNOWN"]["customers"] += 1
    for o in db.query(SalesOrder).all():
        k = o.source_channel or "UNKNOWN"
        agg[k]["orders"] += 1
        agg[k]["amount"] += num(o.total)
    return [{"channel": k, **v} for k, v in agg.items()]


@router.get("/profit")
def profit_report(request: Request, actor: Actor = Depends(require("report", "view")), db=Depends(get_db)):
    data = list_resource(db, OrderProfit, actor, "report", request)
    for row in data["items"]:
        o = db.get(SalesOrder, row["order_id"])
        row["order_no"] = o.order_no if o else ""
    return data


@router.get("/funnel")
def funnel(_=Depends(require("report", "view")), db=Depends(get_db)):
    return [{"stage": "线索", "count": db.query(Lead).count()},
            {"stage": "报价", "count": db.query(Quotation).count()},
            {"stage": "订单", "count": db.query(SalesOrder).count()},
            {"stage": "回款", "count": db.query(Payment).filter_by(direction="IN").count()}]


@router.get("/inventory-health")
def inventory_health(_=Depends(require("report", "view")), db=Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(days=90)
    recent = {m.product_id for m in db.query(StockMove).filter(StockMove.created_at >= cutoff).all()}
    rows = []
    for b in db.query(StockBalance).all():
        p = db.get(Product, b.product_id)
        if not p:
            continue
        rows.append({"code": p.code, "name": p.name_en or p.name_cn, "qty": num(b.qty),
                     "available": num(b.qty) - num(b.allocated_qty),
                     "low": num(b.qty) < num(p.safety_stock),
                     "idle_90d": b.product_id not in recent})
    return rows


@router.get("/commissions")
def commission_report(request: Request, actor: Actor = Depends(require("report", "view")), db=Depends(get_db)):
    return list_resource(db, Commission, actor, "report", request, like_fields=("user_name", "period"))
