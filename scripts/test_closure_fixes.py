"""端到端 6：闭环防护回归（v1.0.1）。

验证本轮补齐的业务边界：核销不超应收、超额外付进审批中心、写接口鉴权、
主数据删除保护、出运扣减实物库存、状态机不卡死、前端按钮白名单与后端路由一致。
用法：cd backend && python ../scripts/test_closure_fixes.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erp_test_utils import ERP, report  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _items(data):
    return data["items"] if isinstance(data, dict) else data


def check_frontend_whitelist():
    """静态校验：通用列表页按钮白名单里的每个资源，后端确实有对应方法。"""
    menu = (ROOT / "frontend/src/menu.js").read_text(encoding="utf-8")
    pairs = {}
    for key, endpoint in re.findall(r"\n  '?([A-Za-z0-9_-]+)'?: *\{\s*\n?[^\n]*?endpoint: *'([^']+)'", menu):
        pairs[key] = endpoint
    # 兼容上面正则未覆盖的写法：按资源块逐个取端点
    if not pairs:
        blocks = re.split(r"\n  '?([A-Za-z0-9_-]+)'?: *\{", menu)
        for i in range(1, len(blocks) - 1, 2):
            m = re.search(r"endpoint: *'([^']+)'", blocks[i + 1][:600])
            if m:
                pairs[blocks[i]] = m.group(1)
    routes = []
    for f in sorted((ROOT / "backend/app/api").glob("*.py")):
        s = f.read_text(encoding="utf-8")
        m = re.search(r'APIRouter\(prefix="([^"]+)"', s)
        prefix = m.group(1) if m else ""
        for x in re.finditer(r'@router\.(get|post|put|delete)\("([^"]+)"', s):
            routes.append((x.group(1).upper(), prefix + x.group(2)))
    bases = {m: {r[1].split("/{")[0] for r in routes if r[0] == m}
             for m in ("POST", "PUT", "DELETE")}
    for name, method in (("CREATABLE", "POST"), ("EDITABLE", "PUT"), ("DELETABLE", "DELETE")):
        m = re.search(r"export const " + name + r" = new Set\(\[(.*?)\]\)", menu, re.S)
        assert m, f"menu.js 缺少 {name}"
        keys = set(re.findall(r"'([^']+)'", m.group(1)))
        missing = [k for k in keys if "/api" + pairs.get(k, "@@") not in bases[method]]
        assert not missing, f"{name} 存在后端无 {method} 的死链资源：{missing}"
    return len(pairs)


def main():
    e = ERP()
    c = e.new_customer(currency="USD")
    o = e.post("/orders", {"customer_id": c["id"], "currency": "USD", "exchange_rate": 7.12,
                           "items": [{"product_id": 1, "oe_no": "25100-03011",
                                      "name_snapshot": "Oil Filter", "qty": 2, "unit_price": 10}]})
    assert float(o["total"]) == 20.0, f"订单金额异常 {o['total']}"

    # 1. 核销不得超订单应收（原来只校验付款单余额）
    p = e.post("/payments", {"direction": "IN", "method": "TT", "customer_id": c["id"],
                             "amount": 1000, "currency": "USD", "exchange_rate": 7.12})
    e.post(f"/payments/{p['id']}/allocate",
           {"target_type": "ORDER", "target_id": o["id"], "amount": 25}, expect=400)
    e.post(f"/payments/{p['id']}/allocate",
           {"target_type": "ORDER", "target_id": o["id"], "amount": 20})
    e.post(f"/payments/{p['id']}/allocate",
           {"target_type": "ORDER", "target_id": o["id"], "amount": 1}, expect=400)
    assert e.get(f"/orders/{o['id']}")["status"] == "READY_SHIP", "全款未驱动到待出运"

    # 2. 出运扣减实物库存并生成 OUT_SALE 流水，同步释放订单占用
    lines = e.get(f"/orders/{o['id']}")["items"]
    e.post("/shipments", {"order_id": o["id"], "items": [
        {"order_item_id": lines[0]["id"], "product_id": 1, "name_snapshot": "Oil Filter",
         "oe_no": "25100-03011", "qty": 2, "amount": 20}]})
    moves = _items(e.get("/stock-moves?move_type=OUT_SALE&size=100"))
    assert moves, "出运未生成 OUT_SALE 库存流水"

    # 3. 超额外付自动生成审批单，审批中心可见
    out = e.post("/payments", {"direction": "OUT", "method": "TT", "amount": 99999,
                               "currency": "CNY", "exchange_rate": 1})
    assert out["approval_status"] == "PENDING", "超额外付未进入待审批"
    approvals = _items(e.get("/approvals?size=100"))
    assert any(a.get("ref_type") == "payment" and a.get("ref_no") == out["payment_no"]
               and a.get("status") == "PENDING" for a in approvals), "待审批付款单没有对应审批记录"

    # 4. 手动催办是写接口，不能匿名调用
    r = e.client.post("/api/system/reminders/run")
    assert r.status_code in (401, 403), f"催办接口未鉴权：{r.status_code}"
    e.post("/system/reminders/run")

    # 5. 被引用的主数据禁止删除
    e.call("delete", "/products/1", expect=400)

    # 6. 采购建议补在途字段；利润列表补订单号
    suggestions = e.get("/purchase-suggestions")
    assert isinstance(suggestions, list)
    assert all("in_transit" in s for s in suggestions), "采购建议缺少在途量字段"
    profits = _items(e.get("/order-profits?size=100"))
    assert profits and all("order_no" in x for x in profits), "利润列表缺少订单号"

    # 7. 已转订单的报价不能再次转单
    qs = _items(e.get("/quotations?size=100"))
    converted = next((q for q in qs if q.get("status") == "CONVERTED"), None)
    if converted:
        e.post(f"/quotations/{converted['id']}/convert", {}, expect=400)

    # 8. 前端按钮白名单与后端真实路由一致
    n = check_frontend_whitelist()
    report("闭环防护回归", e, f"| 核销上限 / 审批闭环 / 出运扣库存 / 删除保护 / 白名单 {n} 资源 全部通过")
    e.close()


if __name__ == "__main__":
    main()
