"""端到端 5：v2.1 进销存闭环（盘点盘亏调账 / 采购退货出库 + 自动退款审批单）。"""
from erp_test_utils import ERP, report


def _stock_in(e, product_id=1, qty=100, price=12.2):
    po = e.post("/purchase-orders", {"supplier_id": 1, "currency": "CNY",
                                     "items": [{"product_id": product_id,
                                                "name_snapshot": "Oil Filter",
                                                "qty": qty, "price": price}]})
    item = e.get(f"/purchase-orders/{po['id']}")["items"][0]
    e.post(f"/purchase-orders/{po['id']}/receive", {"item_id": item["id"], "qty": qty})
    return po


def main():
    e = ERP()
    _stock_in(e, qty=100)

    # ---- 盘点：账面快照 → 实盘差异 → 确认生成 ADJUST 流水 ----
    t = e.post("/stocktakes", {"warehouse_id": 1, "note": "端到端测试盘点"})
    detail = e.get(f"/stocktakes/{t['id']}")
    assert detail["items"], "盘点单未锁定账面快照"
    target = next(i for i in detail["items"] if i["product_id"] == 1)
    book = float(target["book_qty"])
    e.put(f"/stocktakes/{t['id']}/items", {"items": [
        {"id": target["id"], "real_qty": book - 5, "note": "盘亏 5"}]})
    confirmed = e.post(f"/stocktakes/{t['id']}/confirm", {})
    assert confirmed["adjusted_lines"] >= 1, "确认后未生成调账流水"
    adjust = [m for m in e.get("/stock-moves")["items"]
              if m["move_type"] == "ADJUST" and m["ref_no"] == t["take_no"]]
    assert adjust and any(float(m["qty"]) == -5 for m in adjust), "盘亏流水不正确"
    assert e.get(f"/stocktakes/{t['id']}/export").startswith(b"PK")

    # ---- 采购退货：关联采购单自动带明细 → 出库 → 自动退款付款单 ----
    po = _stock_in(e, qty=30, price=11.0)
    r = e.post("/purchase-returns", {"purchase_order_id": po["id"], "supplier_id": 1,
                                     "warehouse_id": 1, "note": "质检不合格退货"})
    assert r["return_no"].startswith("TH")
    # 确认并校验副作用：OUT_RETURN 流水 + REFUND 付款单
    res = e.post(f"/purchase-returns/{r['id']}/confirm", {})
    assert res["total"] > 0, "退货金额应为正数"
    out_moves = [m for m in e.get("/stock-moves")["items"]
                 if m["move_type"] == "OUT_RETURN" and m["ref_no"] == r["return_no"]]
    assert out_moves, "未生成退货出库流水"
    refunds = [p for p in e.get("/payments")["items"] if p["method"] == "REFUND"]
    assert refunds and any(p["approval_status"] == "PENDING" for p in refunds), \
        "未自动生成进入审批流的退款付款单"
    report("盘点 / 采购退货闭环", e, "| ADJUST 调账 / OUT_RETURN / REFUND 审批 全部通过")
    e.close()


if __name__ == "__main__":
    main()
