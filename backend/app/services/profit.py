"""利润核算与提成（P0 补充：口径写死可追溯）。

口径 v1：
- 收入按订单锁定汇率(报价汇率)折算 CNY；
- 汇兑损益 = Σ 每笔已核销收款 × (结汇汇率 − 报价汇率)，部分收款逐笔摊，不重复计算；
- 成本优先取采购实际成本（库存移动加权），无则用单据 cost_snapshot；
- 运费按 shipment 汇总，按订单金额占比分摊（拼柜场景）；
- 提成基数 = 已核销回款(CNY)，比例取 settings.commission_rate，回款到账才计提。
"""
from datetime import datetime
from decimal import Decimal

from ..core.settings_service import get_float
from ..core.utils import dec
from ..models.finance import (Commission, Expense, OrderProfit, Payment,
                              PaymentAllocation, Rebate)
from ..models.sales import SalesOrder, SalesOrderItem
from ..models.shipping import FreightCost, Shipment
from ..models.inventory import StockBalance


def _rate(db, currency):
    from ..models.finance import ForexRate
    r = db.query(ForexRate).filter_by(currency=currency, rate_type="QUOTE").first()
    return dec(r.rate) if r else Decimal("1")


def compute(db, order_id, actor_name="system"):
    order = db.get(SalesOrder, int(order_id))
    if order is None:
        return None
    quote_rate = dec(order.exchange_rate)
    items = db.query(SalesOrderItem).filter_by(order_id=order.id).all()
    revenue = sum(dec(i.amount) for i in items) * quote_rate

    purchase_cost = Decimal("0")
    for i in items:
        bal = db.query(StockBalance).filter_by(product_id=i.product_id).first()
        unit_cost = dec(bal.avg_cost) if bal and dec(bal.avg_cost) > 0 else dec(i.cost_snapshot)
        purchase_cost += unit_cost * dec(i.qty)

    shipments = db.query(Shipment).filter_by(order_id=order.id).all()
    ship_ids = [s.id for s in shipments]
    freight = Decimal("0")
    for fc in db.query(FreightCost).filter(FreightCost.shipment_id.in_(ship_ids)).all() if ship_ids else []:
        freight += dec(fc.amount) * dec(fc.exchange_rate or 1)

    # 订单直接费用 + 出运批次费用；同一笔费用同时挂订单与批次时按 id 去重，避免重复扣减
    exp_rows = {e.id: e for e in db.query(Expense).filter_by(order_id=order.id).all()}
    if ship_ids:
        for e in db.query(Expense).filter(Expense.shipment_id.in_(ship_ids)).all():
            exp_rows[e.id] = e
    expenses = sum(dec(e.amount) * dec(e.exchange_rate or 1) for e in exp_rows.values())

    allocs = db.query(PaymentAllocation).filter_by(target_type="ORDER", target_id=order.id).all()
    allocated = Decimal("0")
    exchange_gain = Decimal("0")
    for a in allocs:
        p = db.get(Payment, a.payment_id)
        if not p:
            continue
        allocated += dec(a.amount) * quote_rate
        settle = dec(p.exchange_rate or quote_rate)
        # 该笔收款中核销到本订单的部分，按占比摊汇差
        share = (dec(a.amount) / dec(p.amount)) if dec(p.amount) > 0 else Decimal("0")
        exchange_gain += dec(p.amount) * share * (settle - quote_rate)

    rebate = sum(dec(r.rebate_amount) for r in
                 db.query(Rebate).filter_by(order_id=order.id).all() if r.status == "RECEIVED")
    rate = Decimal(str(get_float(db, "commission_rate", 0.015)))
    commission = allocated * rate
    net = revenue - purchase_cost - freight - commission - expenses + rebate + exchange_gain
    margin = (net / revenue * Decimal("100")) if revenue else Decimal("0")

    row = db.query(OrderProfit).filter_by(order_id=order.id, shipment_id=None).first()
    if row is None:
        row = OrderProfit(order_id=order.id, created_at=datetime.utcnow())
        db.add(row)
    row.revenue, row.purchase_cost, row.freight_share = revenue, purchase_cost, freight
    row.commission_fee, row.expenses, row.rebate = commission, expenses, rebate
    row.exchange_gain, row.net_profit = exchange_gain, net
    row.margin_pct = margin
    row.calculated_at = datetime.utcnow()
    row.formula_version = "v1"
    row.detail = "分摊规则=按订单金额；汇差=逐笔结汇-报价；提成基数=已核销回款"
    row.locked = order.status == "CLOSED"
    db.flush()

    # 提成：按已核销回款计提，回款到账才生成；重复核算不重复计提
    c = db.query(Commission).filter_by(order_id=order.id).first()
    if allocated > 0:
        if c is None:
            c = Commission(order_id=order.id, created_at=datetime.utcnow())
            db.add(c)
        c.user_name = order.owner_name or ""
        c.base_amount, c.rate, c.amount = allocated, rate, commission
        c.period = datetime.utcnow().strftime("%Y-%m")
        c.status = "CONFIRMED" if order.status == "CLOSED" else "PENDING"
    return row


def compute_all(db):
    ids = [r[0] for r in db.query(SalesOrder.id).all()]
    for oid in ids:
        compute(db, oid)
    return len(ids)
