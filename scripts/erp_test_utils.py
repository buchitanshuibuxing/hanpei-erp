"""端到端测试公共客户端：进程内 TestClient，无需启动服务。"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def uid(prefix="T"):
    return prefix + uuid.uuid4().hex[:8].upper()


class ERP:
    def __init__(self, username="admin", password="admin123"):
        self.client = TestClient(app)
        self.client.__enter__()
        r = self.client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, f"登录失败：{r.text}"
        self.headers = {"Authorization": "Bearer " + r.json()["token"]}
        self.count = 0
        self.pdf_hits = 0

    def call(self, method, path, payload=None, expect=200, headers=None):
        if not path.startswith("/api/"):
            path = "/api/" + path.lstrip("/")
        merged = dict(self.headers)
        merged.update(headers or {})
        kwargs = {"headers": merged}
        if payload is not None:
            kwargs["json"] = payload
        r = getattr(self.client, method)(path, **kwargs)
        self.count += 1
        if r.status_code != expect:
            raise AssertionError(f"{method.upper()} {path} 期望 {expect}，实际 {r.status_code}：{r.text[:500]}")
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype:
            return r.json()
        if r.content.startswith(b"%PDF"):
            self.pdf_hits += 1
        return r.content

    def get(self, path, expect=200, **kw):
        return self.call("get", path, expect=expect, **kw)

    def post(self, path, payload=None, expect=200, **kw):
        return self.call("post", path, payload, expect=expect, **kw)

    def put(self, path, payload=None, expect=200, **kw):
        return self.call("put", path, payload, expect=expect, **kw)

    def portal(self, username="alnoor", password="portal123"):
        r = self.client.post("/api/auth/portal/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def new_customer(self, currency="USD", policy="NEW_DEPOSIT", owner="李业务"):
        return self.post("/customers", {"name": uid("Customer "), "country": "SA",
                                        "currency": currency, "payment_policy": policy,
                                        "payment_terms_days": 30, "owner_name": owner})

    def new_order(self, customer_id, qty=10, price=30, currency="USD", policy_amount=None):
        return self.post("/orders", {"customer_id": customer_id, "currency": currency,
                                     "exchange_rate": 7.12 if currency == "USD" else 1.897,
                                     "items": [{"product_id": 1, "oe_no": "25100-03011",
                                                "name_snapshot": "Oil Filter", "qty": qty,
                                                "unit_price": price}]})

    def close(self):
        self.client.__exit__(None, None, None)


def report(name, erp, extra=""):
    print(f"[PASS] {name}: {erp.count} 次请求, {erp.pdf_hits} 份 PDF {extra}")
