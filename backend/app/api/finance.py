"""财务：收付款核销、审批、银行/汇率、退税、费用、利润、提成、账龄、售后索赔、对账。"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.audit import audit
from ..core.crud import create_resource, list_resource, update_resource
from ..core.deps import Actor, require
from ..core.numbering import next_no
from ..core.settings_service import get_float
from ..core.utils import dec, num, paged, row_dict
from ..db import get_db
from ..models.crm import Customer
from ..models.finance import (AfterSalesClaim, BankAccount, Commission,
                              Expense, ForexRate, Forwarder, OrderProfit,
                              Payment, PaymentAllocation, Rebate, Refund)
from ..models.sales import Quotation, SalesOrder
from ..models.system import ApprovalRequest
from ..services.excel import export_excel
from ..services.order_state import apply_receipt, received_total
from ..services.profit import compute, compute_all
from .helpers import xlsx_response

router = APIRouter(prefix="/api", tags=["财务管理"])


def _remaining(db, payment):
    used = sum(dec(a.amount) for a in db.query(PaymentAllocation).filter_by(payment_id=payment.id).all())
    return dec(payment.amount) - used


# ---------------- 收款与核销 ----------------
@router.get("/payments")
def list_payments(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    data = list_resource(db, Payment, actor, "finance", request, like_fields=("payment_no", "water_bill_no"))
    for row in data["items"]:
        row["remaining"] = float(_remaining(db, db.get(Payment, row["id"])))
    return data


@router.post("/payments")
def create_payment(body: dict, actor: Actor = Depends(require("finance", "create")), db=Depends(get_db)):
    payload = dict(body)
    payload.setdefault("payment_no", next_no(db, "PAYMENT"))
    payload.setdefault("received_at", datetime.utcnow())
    payload.setdefault("exchange_rate", 1)
    rate = dec(payload.get("exchange_rate") or 1)
    amount = dec(payload.get("amount") or 0)
    fee = dec(payload.get("fee_amount") or 0)
    payload["net_amount"] = amount - fee
    payload["base_amount"] = amount * rate
    limit = get_float(db, "approve_limit", 50000)
    if payload.get("direction", "IN") == "OUT" and float(amount) > limit:
        payload["approval_status"] = "PENDING"
    row = create_resource(db, Payment, payload, actor, module="finance")
    audit(db, actor, "payment.create", "payments", row.id, detail=f"登记 {row.payment_no}")
    db.commit()
    return {"id": row.id, "payment_no": row.payment_no, "approval_status": row.approval_status}


class AllocateIn(BaseModel):
    target_type: str = "ORDER"
    target_id: int
    amount: float


@router.post("/payments/{pid}/allocate")
def allocate_payment(pid: int, body: AllocateIn, actor: Actor = Depends(require("finance", "edit")), db=Depends(get_db)):
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "付款单不存在")
    if p.approval_status == "PENDING":
        raise HTTPException(400, "该付款单待审批，不能核销")
    amt = dec(body.amount)
    if amt <= 0 or amt > _remaining(db, p) + Decimal("0.000001"):
        raise HTTPException(400, f"核销金额超过未核销余额 {_remaining(db, p)}")
    db.add(PaymentAllocation(created_at=datetime.utcnow(), payment_id=pid,
                             target_type=body.target_type, target_id=body.target_id, amount=amt))
    db.flush()
    remaining = _remaining(db, p)
    p.status = "ALLOCATED" if remaining <= 0 else "UNALLOCATED"
    if body.target_type == "ORDER":
        order = db.get(SalesOrder, body.target_id)
        if order:
            apply_receipt(db, order, actor, payment_id=pid)
            compute(db, order.id, actor.name)
    audit(db, actor, "payment.allocate", "payments", pid,
          detail=f"核销 {body.target_type}#{body.target_id} {amt}")
    db.commit()
    return {"message": "核销成功", "remaining": float(remaining)}


@router.get("/payments/{pid}/allocations")
def payment_allocations(pid: int, _=Depends(require("finance", "view")), db=Depends(get_db)):
    return [row_dict(a) for a in db.query(PaymentAllocation).filter_by(payment_id=pid).all()]


# ---------------- 审批 ----------------
@router.get("/approvals")
def approvals(request: Request, actor: Actor = Depends(require("finance", "approve")), db=Depends(get_db)):
    return list_resource(db, ApprovalRequest, actor, "finance", request)


@router.post("/approvals/{aid}/decide")
def decide_approval(aid: int, body: dict, actor: Actor = Depends(require("finance", "approve")), db=Depends(get_db)):
    a = db.get(ApprovalRequest, aid)
    if not a or a.status != "PENDING":
        raise HTTPException(400, "审批单不存在或已处理")
    status = "APPROVED" if body.get("approve") else "REJECTED"
    a.status, a.approver, a.decided_at = status, actor.name, datetime.utcnow()
    a.reason = body.get("reason", "")
    if a.flow_type == "DISCOUNT" and a.ref_type == "quotation":
        q = db.get(Quotation, a.ref_id)
        if q:
            q.status = "DRAFT" if status == "APPROVED" else "REJECTED"
            q.approved_by = actor.name if status == "APPROVED" else None
    if a.ref_type == "payment":
        p = db.get(Payment, a.ref_id)
        if p:
            p.approval_status = status
    audit(db, actor, f"approval.{status.lower()}", "approval_requests", aid, detail=a.ref_no or "")
    db.commit()
    return {"status": status}


# ---------------- 基础资料 ----------------
@router.get("/bank-accounts")
def bank_accounts(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, BankAccount, actor, "finance", request, like_fields=("bank_name", "beneficiary"))


@router.post("/bank-accounts")
def add_bank_account(body: dict, actor: Actor = Depends(require("finance", "create")), db=Depends(get_db)):
    if actor.role not in ("FINANCE", "ADMIN", "MANAGER"):
        raise HTTPException(403, "收款账户仅财务/管理员可维护")
    row = create_resource(db, BankAccount, body, actor)
    audit(db, actor, "bank.change", "bank_accounts", row.id, detail="新增收款账户")
    db.commit()
    return row_dict(row)


@router.put("/bank-accounts/{bid}")
def update_bank_account(bid: int, body: dict, actor: Actor = Depends(require("finance", "edit")), db=Depends(get_db)):
    if actor.role not in ("FINANCE", "ADMIN", "MANAGER"):
        raise HTTPException(403, "收款账户仅财务/管理员可维护")
    before = row_dict(db.get(BankAccount, bid))
    update_resource(db, BankAccount, bid, body, actor)
    audit(db, actor, "bank.change", "bank_accounts", bid, detail="修改收款账户", before=before)
    db.commit()
    return {"message": "已保存"}


@router.get("/forex-rates")
def forex_rates(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, ForexRate, actor, "finance", request)


@router.post("/forex-rates")
def add_forex(body: dict, actor: Actor = Depends(require("finance", "edit")), db=Depends(get_db)):
    row = create_resource(db, ForexRate, body, actor,
                          defaults={"effective_date": date.today(), "source": "MANUAL"})
    audit(db, actor, "forex.change", "forex_rates", row.id, detail="维护汇率")
    db.commit()
    return row_dict(row)


@router.get("/forex-rates/status")
def forex_status(_=Depends(require("finance", "view")), db=Depends(get_db)):
    stale_days = get_float(db, "forex_stale_days", 7)
    out = []
    for cur in ("USD", "SAR", "AED", "CNY"):
        r = db.query(ForexRate).filter_by(currency=cur, rate_type="QUOTE").order_by(ForexRate.id.desc()).first()
        age = (date.today() - r.effective_date).days if r and r.effective_date else 999
        out.append({"currency": cur, "rate": num(r.rate) if r else None,
                    "effective_date": str(r.effective_date or "") if r else "",
                    "stale": age > stale_days, "age_days": age})
    return out


@router.get("/forwarders")
def forwarders(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, Forwarder, actor, "finance", request, like_fields=("name",))


@router.post("/forwarders")
def add_forwarder(body: dict, actor: Actor = Depends(require("finance", "create")), db=Depends(get_db)):
    row = create_resource(db, Forwarder, body, actor)
    db.commit()
    return row_dict(row)


# ---------------- 退税 / 费用 / 利润 / 提成 ----------------
@router.get("/rebates")
def rebates(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, Rebate, actor, "finance", request, like_fields=("order_no", "customs_doc_no"))


@router.post("/rebates")
def add_rebate(body: dict, actor: Actor = Depends(require("finance", "create")), db=Depends(get_db)):
    row = create_resource(db, Rebate, body, actor)
    db.commit()
    return row_dict(row)


@router.put("/rebates/{rid}")
def update_rebate(rid: int, body: dict, actor: Actor = Depends(require("finance", "edit")), db=Depends(get_db)):
    update_resource(db, Rebate, rid, body, actor, module="finance")
    db.commit()
    return {"message": "已保存"}


@router.get("/expenses")
def expenses(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, Expense, actor, "finance", request)


@router.post("/expenses")
def add_expense(body: dict, actor: Actor = Depends(require("finance", "create")), db=Depends(get_db)):
    row = create_resource(db, Expense, body, actor)
    db.commit()
    return row_dict(row)


@router.get("/order-profits")
def order_profits(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, OrderProfit, actor, "finance", request)


@router.post("/order-profits/recalculate")
def recalculate(_=Depends(require("finance", "edit")), db=Depends(get_db)):
    n = compute_all(db)
    db.commit()
    return {"recalculated": n, "formula_version": "v1"}


@router.get("/commissions")
def commissions(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, Commission, actor, "finance", request, like_fields=("user_name", "period"))


@router.post("/commissions/{cid}/pay")
def pay_commission(cid: int, actor: Actor = Depends(require("finance", "approve")), db=Depends(get_db)):
    c = db.get(Commission, cid)
    if not c:
        raise HTTPException(404, "提成记录不存在")
    c.status = "PAID"
    audit(db, actor, "commission.pay", "commissions", cid, detail="标记发放")
    db.commit()
    return {"status": c.status}


@router.get("/refunds")
def refunds(request: Request, actor: Actor = Depends(require("finance", "view")), db=Depends(get_db)):
    return list_resource(db, Refund, actor, "finance", request)


# ---------------- 应收账龄 ----------------
@router.get("/receivables/aging")
def receivables_aging(_=Depends(require("finance", "view")), db=Depends(get_db)):
    """账龄按 due_date 起算（P0 补充口径），无账期则按交期。"""
    buckets = {"current": 0.0, "d30": 0.0, "d60": 0.0, "d90": 0.0, "over90": 0.0}
    rows = []
    for o in db.query(SalesOrder).filter(SalesOrder.status.notin_(["CLOSED", "CANCELLED"])).all():
        remain = dec(o.total) - received_total(db, o.id)
        if remain <= 0:
            continue
        base = o.due_date or o.delivery_date or (o.created_at.date() if o.created_at else date.today())
        days = (date.today() - base).days
        key = "current" if days <= 0 else "d30" if days <= 30 else "d60" if days <= 60 else "d90" if days <= 90 else "over90"
        buckets[key] += float(remain)
        c = db.get(Customer, o.customer_id)
        rows.append({"order_no": o.order_no, "customer": c.name if c else "",
                     "owner": o.owner_name, "currency": o.currency,
                     "remain": float(remain), "due_date": str(base), "days": days, "bucket": key})
    return {"buckets": buckets, "rows": rows}


# ---------------- 售后索赔（P0 补充） ----------------
@router.get("/claims")
def claims(request: Request, actor: Actor = Depends(require("claim", "view")), db=Depends(get_db)):
    return list_resource(db, AfterSalesClaim, actor, "claim", request, like_fields=("claim_no", "reason"))


@router.post("/claims")
def add_claim(body: dict, actor: Actor = Depends(require("claim", "create")), db=Depends(get_db)):
    payload = dict(body)
    payload.setdefault("claim_no", next_no(db, "CLAIM"))
    row = create_resource(db, AfterSalesClaim, payload, actor, module="claim")
    db.commit()
    return row_dict(row)


@router.post("/claims/{cid}/resolve")
def resolve_claim(cid: int, body: dict, actor: Actor = Depends(require("claim", "approve")), db=Depends(get_db)):
    c = db.get(AfterSalesClaim, cid)
    if not c or c.status == "CLOSED":
        raise HTTPException(400, "索赔单不存在或已结案")
    c.resolution, c.responsibility = body.get("resolution", "REFUND"), body.get("responsibility", "UNKNOWN")
    c.status, c.resolved_at = "CLOSED", datetime.utcnow()
    if c.resolution in ("REFUND", "OFFSET"):
        db.add(Refund(order_id=c.order_id, customer_id=c.customer_id, amount=dec(c.amount),
                      type=c.resolution, reason=c.reason, status="PENDING",
                      created_at=datetime.utcnow(), created_by=actor.name))
    if c.order_id:
        compute(db, c.order_id, actor.name)
    audit(db, actor, "claim.resolve", "after_sales_claims", cid, detail=c.resolution)
    db.commit()
    return {"status": c.status}


# ---------------- 三方对账 ----------------
@router.get("/finance/reconciliation")
def reconciliation(kind: str = "CUSTOMER", _=Depends(require("finance", "view")), db=Depends(get_db)):
    if kind == "CUSTOMER":
        rows = []
        for c in db.query(Customer).all():
            orders = db.query(SalesOrder).filter_by(customer_id=c.id).all()
            total = sum(dec(o.total) for o in orders)
            paid = sum(received_total(db, o.id) for o in orders)
            rows.append({"name": c.name, "currency": c.currency, "order_total": float(total),
                         "received": float(paid), "balance": float(total - paid)})
        return rows
    if kind == "FORWARDER":
        rows = []
        for f in db.query(Forwarder).all():
            pays = db.query(Payment).filter_by(forwarder_id=f.id).all()
            rows.append({"name": f.name,
                         "gross": float(sum(dec(p.amount) for p in pays)),
                         "fee": float(sum(dec(p.fee_amount) for p in pays)),
                         "net": float(sum(dec(p.net_amount) for p in pays))})
        return rows
    from ..models.crm import Supplier
    from ..models.purchase import PurchaseOrder
    rows = []
    for s in db.query(Supplier).all():
        pos = db.query(PurchaseOrder).filter_by(supplier_id=s.id).all()
        rows.append({"name": s.name, "po_amount": float(sum(dec(p.total) for p in pos)),
                     "po_count": len(pos)})
    return rows


@router.get("/finance/export")
def finance_export(kind: str = "profits", actor: Actor = Depends(require("finance", "export")), db=Depends(get_db)):
    if kind == "commissions":
        headers, rows = ["业务员", "订单", "月份", "基数", "比例", "提成", "状态"], []
        for c in db.query(Commission).all():
            rows.append([c.user_name, c.order_id, c.period, num(c.base_amount), num(c.rate),
                         num(c.amount), c.status])
    elif kind == "rebates":
        headers, rows = ["订单号", "报关单号", "发票号", "退税金额", "状态", "到账日"], []
        for r in db.query(Rebate).all():
            rows.append([r.order_no, r.customs_doc_no, r.invoice_no, num(r.rebate_amount),
                         r.status, str(r.received_at or "")])
    else:
        headers, rows = ["订单ID", "收入", "采购成本", "运费", "佣金", "费用", "退税", "汇差", "净利", "毛利率%"], []
        for p in db.query(OrderProfit).all():
            rows.append([p.order_id, num(p.revenue), num(p.purchase_cost), num(p.freight_share),
                         num(p.commission_fee), num(p.expenses), num(p.rebate),
                         num(p.exchange_gain), num(p.net_profit), num(p.margin_pct)])
    return xlsx_response(export_excel(headers, rows, kind), f"{kind}.xlsx")
