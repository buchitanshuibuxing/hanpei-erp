"""全链路冒烟：询报价 → 订单 → 收款核销 → 采购入库 → 分批出运 → 装箱单 → 报表。

用法：cd backend && python ../scripts/smoke_api.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

STEP = 0


def call(c, method, path, payload=None, headers=None, expect=200, label=""):
    global STEP
    STEP += 1
    kwargs = {"headers": headers or {}}
    if payload is not None:
        kwargs["json"] = payload
    r = getattr(c, method)(path, **kwargs)
    ok = r.status_code == expect
    body = r.text[:180] if not r.headers.get("content-type", "").startswith("application/pdf") else "<PDF bytes>"
    print(f"{STEP:02d} {'OK ' if ok else 'FAIL'} {method.upper():4} {path:52} -> {r.status_code} {body}")
    if not ok:
        raise AssertionError(f"{path}: {r.status_code} {r.text[:400]}")
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.content


def main():
    with TestClient(app) as c:
        login = call(c, "post", "/api/auth/login",
                     {"username": "admin", "password": "admin123"}, label="登录")
        H = {"Authorization": f"Bearer {login['token']}"}

        call(c, "get", "/api/products", headers=H)
        call(c, "get", "/api/products/search?oe=25100-03011", headers=H)
        match = call(c, "post", "/api/inquiries/match",
                     {"text": "25100-03011\n17801-30030", "customer_id": 1, "currency": "SAR"}, H)
        assert match["matched"] >= 2, "OE 匹配失败"

        q = call(c, "post", "/api/quotations", {
            "customer_id": 1, "currency": "SAR", "discount_pct": 2,
            "items": [{"product_id": i["product_id"], "oe_no": i["oe_no"],
                       "name_snapshot": i["name_snapshot"], "qty": 20,
                       "unit_price": i["unit_price"]} for i in match["items"]],
        }, H)
        qid = q["id"]
        call(c, "get", f"/api/quotations/{qid}", headers=H)
        call(c, "get", f"/api/quotations/{qid}/pdf", headers=H)
        call(c, "post", f"/api/quotations/{qid}/send", {"channel": "EMAIL"}, H)

        conv = call(c, "post", f"/api/quotations/{qid}/convert", {}, H)
        oid = conv["order_id"]
        detail = call(c, "get", f"/api/orders/{oid}", headers=H)
        total = detail["total"]

        pay = call(c, "post", "/api/payments", {
            "direction": "IN", "method": "TT", "customer_id": 1, "order_id": oid,
            "amount": total, "currency": "SAR", "exchange_rate": 1.897,
            "water_bill_no": "WB-TEST-001",
        }, H)
        call(c, "post", f"/api/payments/{pay['id']}/allocate",
             {"target_type": "ORDER", "target_id": oid, "amount": total}, H)
        after = call(c, "get", f"/api/orders/{oid}", headers=H)
        assert after["status"] in ("READY_SHIP", "PREPARING", "PENDING_BALANCE"), after["status"]

        po = call(c, "post", "/api/purchase-orders", {
            "supplier_id": 1, "currency": "CNY",
            "items": [{"product_id": 1, "name_snapshot": "Oil Filter", "qty": 100, "price": 12.2}],
        }, H)
        po_detail = call(c, "get", f"/api/purchase-orders/{po['id']}", headers=H)
        call(c, "post", f"/api/purchase-orders/{po['id']}/receive",
             {"item_id": po_detail["items"][0]["id"], "qty": 100}, H)
        call(c, "get", "/api/stock-balances", headers=H)

        line = detail["items"][0]
        shp = call(c, "post", "/api/shipments", {
            "order_id": oid,
            "items": [{"order_item_id": line["id"], "product_id": line["product_id"],
                       "name_snapshot": line["name_snapshot"], "oe_no": line["oe_no"],
                       "qty": 5, "ctn_no": "1", "amount": 5 * line["unit_price"]}],
        }, H)
        sid = shp["id"]
        call(c, "post", f"/api/shipments/{sid}/cartons",
             {"ctn_no": "1", "length": 1.26, "width": 1.09, "height": 1.39, "weight": 432}, H)
        call(c, "get", f"/api/shipments/{sid}/container-suggestion", headers=H)
        call(c, "get", f"/api/shipments/{sid}/pl", headers=H)

        call(c, "post", "/api/order-profits/recalculate", {}, H)
        call(c, "get", "/api/order-profits", headers=H)
        call(c, "get", "/api/receivables/aging", headers=H)
        call(c, "get", "/api/reports/dashboard", headers=H)
        call(c, "get", "/api/system/settings", headers=H)
        call(c, "get", "/api/portal/orders", headers={
            "Authorization": "Bearer " + call(c, "post", "/api/auth/portal/login",
                                              {"username": "alnoor", "password": "portal123"})["token"]})
        call(c, "get", "/api/products", headers={
            "Authorization": "Bearer " + call(c, "post", "/api/auth/portal/login",
                                              {"username": "alnoor", "password": "portal123"})["token"]},
             expect=403, label="门户令牌隔离")
        print("\nSMOKE PASSED: full business chain OK")


if __name__ == "__main__":
    main()
