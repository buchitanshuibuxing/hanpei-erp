"""端到端 3：采购库存闭环（采购建议 / 分批到货 / 移动加权成本 / 流水 / 期初导入）。"""
import io
from openpyxl import Workbook

from erp_test_utils import ERP, report, uid


def _xlsx(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main():
    e = ERP()
    assert isinstance(e.get("/purchase-suggestions"), list), "采购建议不可用"
    # 独立产品，避免与历史库存/其他测试共享移动加权成本
    pid = e.post("/products", {"name_cn": "测试滤芯", "name_en": "Test Filter",
                               "oe_numbers": uid("OE"), "standard_price": 20,
                               "cost_price": 12.2, "hs_code": "8421230000"})["id"]

    po = e.post("/purchase-orders", {"supplier_id": 1, "currency": "CNY",
                                     "items": [{"product_id": pid, "name_snapshot": "Test Filter",
                                                "qty": 100, "price": 12.2}]})
    detail = e.get(f"/purchase-orders/{po['id']}")
    item_id = detail["items"][0]["id"]
    # 分批到货 40 + 60
    first = e.post(f"/purchase-orders/{po['id']}/receive", {"item_id": item_id, "qty": 40})
    assert first["status"] == "PARTIAL_RECEIVED"
    second = e.post(f"/purchase-orders/{po['id']}/receive", {"item_id": item_id, "qty": 60})
    assert second["status"] == "RECEIVED"

    balances = e.get("/stock-balances")["items"]
    bal = next(b for b in balances if b["product_id"] == pid and b["warehouse_id"] == 1)
    assert float(bal["qty"]) >= 100, f"库存未正确入库：{bal['qty']}"
    assert abs(float(bal["avg_cost"]) - 12.2) < 0.01, "移动加权成本不符"

    moves = [m for m in e.get("/stock-moves")["items"]
             if m["ref_type"] == "PURCHASE" and m["ref_id"] == po["id"]]
    assert len(moves) == 2, "到货流水应为两笔"
    assert all(m["after_qty"] == m["before_qty"] + m["qty"] for m in moves), "流水前后数量不连续"

    # 期初库存 Excel 导入（真实 multipart）
    data = _xlsx(["产品编码", "仓库", "库存数量", "成本"], [["HP-0002", "WH01", 50, 16.5]])
    r = e.client.post("/api/stock/initial-import",
                      files={"file": ("initial.xlsx", data,
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                      headers=e.headers)
    assert r.status_code == 200 and r.json()["imported"] == 1, r.text
    b2 = next(b for b in e.get("/stock-balances")["items"]
              if b["product_id"] == 2 and b["warehouse_id"] == 1)
    assert float(b2["qty"]) >= 50

    # Excel 导出与库存预警
    assert e.get("/stock/export").startswith(b"PK"), "库存 Excel 导出失败"
    assert e.get("/reports/inventory-health")
    report("采购库存闭环", e, "| 采购建议 / 分批到货 / 成本 / 流水 / 期初导入 全部通过")
    e.close()


if __name__ == "__main__":
    main()
