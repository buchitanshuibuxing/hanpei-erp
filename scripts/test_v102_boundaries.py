"""端到端 7：v1.0.2 四项边界回归（规划附录 E.8 遗留项收口）。

覆盖：
1. 国内 PL 导入单批数量上限 + 以 ShipmentItem 为事实源重算 qty_shipped（重导入不会累加越界）；
2. 报价转单的数据库唯一约束（应用层二次拦截 + 绕过应用层直插仍被唯一索引拒绝）；
3. 门户「确认订单」落库、重复确认计数、内部可查、门户令牌越权、不改写订单状态/金额；
4. 子资源写接口按父记录 owner_name 显式归属校验（而非依赖通用 get_row()）。
"""
import io

from openpyxl import Workbook
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from erp_test_utils import ERP, report, uid


def pl_bytes(qty):
    """构造附录 B 格式的国内装箱单：OE / 数量 / 名称 / 箱号 / 尺寸。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["OE", "数量", "名称", "箱号", "SIZE(M)"])
    ws.append(["25100-03011", qty, "机油滤清器", "CTN-1", "0.4*0.3*0.3"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_pl(e, sid, qty, expect=200):
    r = e.client.post(
        f"/api/shipments/{sid}/pl-import",
        headers=e.headers,
        files={"file": ("pl.xlsx", pl_bytes(qty),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    e.count += 1
    assert r.status_code == expect, (
        f"pl-import({qty}) 期望 {expect}，实际 {r.status_code}：{r.text[:300]}")
    return r.json() if "application/json" in r.headers.get("content-type", "") else r.content


def shipped(e, oid):
    d = e.get(f"/orders/{oid}")
    return float(d["items"][0]["qty_shipped"] or 0)


def main():
    e = ERP()
    extra = []

    # ---------- 1. PL 导入数量上限 / 重导入不绕过累计 ----------
    c = e.new_customer()
    o = e.new_order(c["id"], qty=10, price=20)
    s = e.post("/shipments", {"order_id": o["id"], "items": []})
    sid = s["id"]
    bad = upload_pl(e, sid, 999, expect=400)
    assert "超过订单总量" in str(bad.get("detail", "")), f"越界提示不符：{bad}"
    assert shipped(e, o["id"]) == 0, "越界导入不应污染已出运数量"

    upload_pl(e, sid, 4)
    assert shipped(e, o["id"]) == 4, "合法导入未回写 qty_shipped"
    upload_pl(e, sid, 8)
    assert shipped(e, o["id"]) == 8, "重导入应替换而非累加（8 而非 12）"
    upload_pl(e, sid, 11, expect=400)
    assert shipped(e, o["id"]) == 8, "越界重导入后 qty_shipped 必须保持不变"
    extra.append("PL 单批上限 / 重导入替换 8 而非 12")

    # ---------- 2. 报价转单唯一约束 ----------
    match = e.post("/inquiries/match", {"text": "25100-03011",
                                        "customer_id": c["id"], "currency": "USD"})
    items = [{"product_id": i["product_id"], "oe_no": i["oe_no"],
              "name_snapshot": i["name_snapshot"], "qty": 5,
              "unit_price": i["unit_price"]}
             for i in match["items"] if i["product_id"]]
    q = e.post("/quotations", {"customer_id": c["id"], "currency": "USD", "items": items})
    e.post(f"/quotations/{q['id']}/convert", {})
    e.post(f"/quotations/{q['id']}/convert", {}, expect=400)

    from app.db import SessionLocal, engine
    from app.models.sales import SalesOrder
    idxs = inspect(engine).get_indexes("sales_orders")
    assert any(i["name"] == "uq_sales_orders_quotation_id" and i["unique"] for i in idxs), \
        "数据库层缺少 uq_sales_orders_quotation_id 唯一索引"
    db = SessionLocal()
    try:
        db.add(SalesOrder(order_no=uid("DUP"), quotation_id=q["id"],
                          customer_id=c["id"]))
        db.commit()
        raise AssertionError("唯一索引未生效：重复 quotation_id 直插成功")
    except IntegrityError as exc:
        assert "UNIQUE" in str(exc).upper(), f"不是唯一约束冲突：{exc}"
        db.rollback()
    finally:
        db.close()
    extra.append("转单唯一索引（应用层 + 直插兜底）")

    # ---------- 3. 门户确认落库 ----------
    po = e.new_order(1, qty=5, price=20)  # customer_id=1 = 门户账号 alnoor
    before = e.get(f"/orders/{po['id']}")
    ph = e.portal()
    r1 = e.post(f"/portal/orders/{po['id']}/confirm", {}, headers=ph)
    assert r1["confirmed"] and r1["confirm_count"] == 1, f"首次确认异常：{r1}"
    r2 = e.post(f"/portal/orders/{po['id']}/confirm", {}, headers=ph)
    assert r2["confirm_count"] == 2, f"重复确认未计数：{r2}"

    detail = e.get(f"/orders/{po['id']}")
    assert detail["portal_confirmation"] and detail["portal_confirmation"]["confirm_count"] == 2, \
        "订单详情未回传客户确认摘要"
    assert detail["status"] == before["status"] and detail["total"] == before["total"], \
        "门户确认不应改写订单状态或金额"
    rows = e.get("/portal-confirmations")["items"]
    assert any(r["order_id"] == po["id"] and r["confirm_count"] == 2 for r in rows), \
        "内部「客户确认记录」列表查不到"
    e.get("/portal-confirmations", expect=403, headers=ph)  # 门户令牌不得访问内部接口

    other = e.new_customer()
    foreign = e.new_order(other["id"], qty=3)
    e.post(f"/portal/orders/{foreign['id']}/confirm", {}, expect=404, headers=ph)
    extra.append("门户确认落库 / 重复计数 / 越权 404 / 状态不变")

    # ---------- 4. 子资源父级归属显式校验 ----------
    owned = e.post("/customers", {"name": uid("Owner "), "country": "SA",
                                  "currency": "USD", "payment_policy": "NEW_DEPOSIT",
                                  "owner_name": "陈业务"})
    s1 = ERP("sales1", "123456")  # 李业务
    s1.post("/customer-contacts", {"customer_id": owned["id"],
                                   "name": "越权联系人"}, expect=404)
    e.count += s1.count
    s1.close()
    s2 = ERP("sales2", "123456")  # 陈业务，客户归属人
    ok = s2.post("/customer-contacts", {"customer_id": owned["id"],
                                        "name": "正常联系人"})
    assert ok["customer_id"] == owned["id"]
    s2.post("/customer-contacts", {"customer_id": 99999999, "name": "x"}, expect=404)
    e.count += s2.count
    s2.close()
    e.post("/products/99999999/oe-numbers", {"oe_no": "X-1"}, expect=404)
    extra.append("子资源父级归属（异主 404 / 同主 200 / 父不存在 404）")

    e.close()
    report("v1.0.2 四项边界回归", e, "| " + "；".join(extra))


if __name__ == "__main__":
    main()
