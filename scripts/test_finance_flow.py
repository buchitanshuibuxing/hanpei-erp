"""端到端 4：财务闭环（一收核多单 / 汇差 / 利润 / 提成 / 退税 / 账龄 / 权限 / 幂等）。"""
from erp_test_utils import ERP, report, uid


def main():
    e = ERP()
    c = e.new_customer(currency="USD")
    o1 = e.new_order(c["id"], qty=10, price=30)
    o2 = e.new_order(c["id"], qty=10, price=30)
    total = e.get(f"/orders/{o1['id']}")["total"]

    # 一收核多单：一笔 600 收款分别核销两张 300 订单，结汇汇率高于报价汇率 → 汇兑收益
    idem = {"Idempotency-Key": "test-" + uid("idem")}
    p1 = e.post("/payments", {"direction": "IN", "method": "TT", "customer_id": c["id"],
                              "amount": total * 2, "currency": "USD", "exchange_rate": 7.30},
                headers=idem)
    p2 = e.post("/payments", {"direction": "IN", "method": "TT", "customer_id": c["id"],
                              "amount": total * 2, "currency": "USD", "exchange_rate": 7.30},
                headers=idem)
    assert p1["id"] == p2["id"], "幂等键未生效，重复创建了付款单"
    for oid in (o1["id"], o2["id"]):
        e.post(f"/payments/{p1['id']}/allocate",
               {"target_type": "ORDER", "target_id": oid, "amount": total})
    assert e.get(f"/orders/{o1['id']}")["status"] == "READY_SHIP"

    # 退税到账计入利润
    e.post("/rebates", {"order_id": o1["id"], "order_no": e.get(f"/orders/{o1['id']}")["order_no"],
                        "customs_doc_no": "CD-TEST", "invoice_no": "INV-TEST",
                        "purchase_invoice_no": "PINV-TEST", "rebate_amount": 100,
                        "status": "RECEIVED"})
    e.post("/order-profits/recalculate", {})
    profits = e.get("/order-profits")["items"]
    pr = next(x for x in profits if x["order_id"] == o1["id"])
    assert pr["rebate"] == 100, "退税未计入利润"
    assert pr["exchange_gain"] > 0, "汇兑损益未核算"
    assert pr["formula_version"] == "v1"
    assert pr["revenue"] > pr["purchase_cost"], "利润口径异常"

    # 提成基数 = 已核销回款，比例 1.5%
    commissions = e.get("/commissions")["items"]
    cm = next(x for x in commissions if x["order_id"] == o1["id"])
    expected = total * 7.12 * 0.015
    assert abs(cm["amount"] - expected) < 1.0, f"提成不符：{cm['amount']} vs {expected}"

    # 账龄按 due_date 分档
    aging = e.get("/receivables/aging")
    assert "buckets" in aging and "rows" in aging

    # 银行账号仅财务/管理员；门户令牌不得访问内部接口
    sales = ERP("sales1", "123456")
    sales.post("/bank-accounts", {"beneficiary": "HACK"}, expect=403)
    sales.close()
    portal_h = e.portal()
    e.get("/products", expect=403, headers=portal_h)
    assert isinstance(e.get("/portal/orders", headers=portal_h), list)

    # 三方对账
    assert isinstance(e.get("/finance/reconciliation?kind=CUSTOMER"), list)
    assert isinstance(e.get("/finance/reconciliation?kind=FORWARDER"), list)
    report("财务闭环", e, "| 一收核多单 / 汇差 / 退税 / 提成 / 账龄 / 幂等 / 隔离 全部通过")
    e.close()


if __name__ == "__main__":
    main()
