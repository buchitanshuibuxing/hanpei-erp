"""端到端 1：询报价闭环（OE 归一化 / 自动带价 / 折扣公式 / 审批拦发送 / PDF / 转订单 / 脱敏）。"""
from erp_test_utils import ERP, report


def main():
    e = ERP()
    # 1. OE 归一化三种写法命中同一产品
    for oe in ("25100-03011", "25100%2003011", "2510003011"):
        rows = e.get(f"/products/search?oe={oe}")
        assert any(r["id"] == 1 for r in rows), f"OE {oe} 未命中"
    # 2. 询价匹配（三色结果）
    c = e.new_customer()
    match = e.post("/inquiries/match", {"text": "25100-03011\n17801-30030\nNOT-EXIST-999",
                                         "customer_id": c["id"], "currency": "USD"})
    assert match["matched"] == 2 and len(match["items"]) == 3
    assert match["items"][2]["match_status"] == "UNMATCHED"
    # 3. 报价创建与金额公式
    items = [{"product_id": i["product_id"], "oe_no": i["oe_no"],
              "name_snapshot": i["name_snapshot"], "qty": 20, "unit_price": i["unit_price"]}
             for i in match["items"] if i["product_id"]]
    q = e.post("/quotations", {"customer_id": c["id"], "currency": "USD", "discount_pct": 2,
                               "items": items})
    detail = e.get(f"/quotations/{q['id']}")
    subtotal = sum(i["amount"] for i in detail["items"])
    assert abs(detail["total"] - subtotal * 0.98) < 0.02, "折扣公式不符"
    assert all(i["name_snapshot"] for i in detail["items"]), "行快照缺失"
    # 4. QT 版式 PDF（真实字节）
    pdf = e.get(f"/quotations/{q['id']}/pdf")
    assert pdf.startswith(b"%PDF"), "报价单 PDF 生成失败"
    # 5. 发送打点 → 转订单
    e.post(f"/quotations/{q['id']}/send", {"channel": "EMAIL"})
    conv = e.post(f"/quotations/{q['id']}/convert", {})
    order = e.get(f"/orders/{conv['order_id']}")
    assert len(order["items"]) == len(items), "转订单丢失明细"
    assert abs(order["total"] - detail["total"]) < 0.01
    # 6. 折扣超阈值 → 审批拦发送
    q2 = e.post("/quotations", {"customer_id": c["id"], "currency": "USD", "discount_pct": 10,
                                "items": items})
    assert q2["status"] == "PENDING_APPROVAL"
    e.get(f"/quotations/{q2['id']}/pdf", expect=400)
    approvals = e.get("/approvals")["items"]
    target = next(a for a in approvals if a["ref_no"] == q2["quote_no"])
    e.post(f"/approvals/{target['id']}/decide", {"approve": True})
    assert e.get(f"/quotations/{q2['id']}/pdf").startswith(b"%PDF"), "审批通过后仍不能导出"
    # 7. 业务员成本脱敏 + 银行账号权限
    sales = ERP("sales1", "123456")
    prod = sales.get("/products")["items"][0]
    assert prod["cost_price"] is None, "业务员不应看到成本"
    sales.post("/bank-accounts", {"beneficiary": "x"}, expect=403)
    sales.close()
    report("询报价闭环", e, "| OE 归一化 / 折扣审批 / PDF / 转单 / 脱敏 全部通过")
    e.close()


if __name__ == "__main__":
    main()
