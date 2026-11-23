"""端到端 2：订单履约闭环（老客代收跳定金 / 收款驱动状态 / 分批出运上限 / PI / 状态日志）。"""
from erp_test_utils import ERP, report


def main():
    e = ERP()
    # 老客代收：转单跳过 PENDING_DEPOSIT
    c = e.new_customer(policy="OLD_COLLECTION")
    q = e.post("/quotations", {"customer_id": c["id"], "currency": "USD",
                               "items": [{"product_id": 1, "oe_no": "25100-03011",
                                          "name_snapshot": "Oil Filter", "qty": 10,
                                          "unit_price": 30}]})
    conv = e.post(f"/quotations/{q['id']}/convert", {})
    oid = conv["order_id"]
    assert conv["status"] == "PREPARING", "老客代收单应跳过待收定金"
    total = e.get(f"/orders/{oid}")["total"]
    assert abs(total - 300) < 0.01

    # 收款登记 → 核销 → 全款自动推进到待出运
    pay = e.post("/payments", {"direction": "IN", "method": "TT", "customer_id": c["id"],
                               "order_id": oid, "amount": total, "currency": "USD",
                               "exchange_rate": 7.12})
    e.post(f"/payments/{pay['id']}/allocate",
           {"target_type": "ORDER", "target_id": oid, "amount": total})
    after = e.get(f"/orders/{oid}")
    assert after["status"] == "READY_SHIP", f"全款应推进到 READY_SHIP，实际 {after['status']}"
    assert abs(after["received_amount"] - total) < 0.01
    assert e.get(f"/payments/{pay['id']}/allocations")

    # 分批出运：5 + 5 = 订单数量 10
    line = after["items"][0]
    for qty in (5, 5):
        shp = e.post("/shipments", {"order_id": oid, "items": [{
            "order_item_id": line["id"], "product_id": line["product_id"],
            "name_snapshot": line["name_snapshot"], "oe_no": line["oe_no"],
            "qty": qty, "ctn_no": "1", "amount": qty * 30}]})
        e.post(f"/shipments/{shp['id']}/cartons",
               {"ctn_no": "1", "length": 1.2, "width": 1.0, "height": 1.0, "weight": 200})
        assert e.get(f"/shipments/{shp['id']}/pl").startswith(b"%PDF"), "装箱单 PDF 失败"
    final = e.get(f"/orders/{oid}")
    assert final["status"] == "SHIPPED", f"全部出运应为 SHIPPED，实际 {final['status']}"
    assert len(final["shipments"]) == 2
    assert float(final["items"][0]["qty_shipped"]) == 10

    # 超订单数量出运必须被拦截
    e.post("/shipments", {"order_id": oid, "items": [{
        "order_item_id": line["id"], "product_id": line["product_id"],
        "name_snapshot": "Oil Filter", "qty": 1, "amount": 30}]}, expect=400)

    # PI 与状态留痕
    assert e.get(f"/orders/{oid}/pdf").startswith(b"%PDF"), "PI PDF 失败"
    assert len(final["status_logs"]) >= 3, "状态流转日志缺失"
    assert all(log["trigger"] in ("MANUAL", "PAYMENT", "SHIPMENT", "SYSTEM")
               for log in final["status_logs"])
    report("订单履约闭环", e, "| 代收跳定金 / 收款驱动 / 分批上限 / PI 全部通过")
    e.close()


if __name__ == "__main__":
    main()
