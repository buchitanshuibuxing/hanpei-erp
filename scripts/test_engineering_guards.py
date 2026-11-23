"""端到端 8：工程基建自测（依赖锁定 / CI / 422 中文 / 500 不泄密）。

对标同类开源 ERP 后新增的工程防护，需可复验、不能被后续改动悄悄破坏。
"""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

from erp_test_utils import ERP, report

ROOT = Path(__file__).resolve().parents[1]


def main():
    e = ERP()

    # 1. 依赖锁定：requirements.txt 里每个直接依赖都必须在 constraints.txt 有精确版本
    req = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    con = (ROOT / "backend" / "constraints.txt").read_text(encoding="utf-8")
    pkgs = [line.split(">=")[0].split("==")[0].strip().split("[")[0]
            for line in req.splitlines() if line.strip() and not line.startswith("#")]
    locked = {line.split("==")[0].strip().split("[")[0]
              for line in con.splitlines() if "==" in line and not line.lstrip().startswith("#")}
    missing = [p for p in pkgs if p not in locked]
    assert not missing, f"以下依赖未锁定精确版本：{missing}"
    assert "alembic" in locked, "alembic 缺失会导致 Docker 启动时 alembic upgrade head 失败"
    # pip 新 resolver 禁止 constraints 出现 extras（psycopg[binary]==x 会让真实部署直接失败），
    # 静态检查不够，必须挡住这种写法重新混进来。
    bad_extras = [line.strip() for line in con.splitlines()
                  if "==" in line and not line.lstrip().startswith("#") and "[" in line]
    assert not bad_extras, f"constraints.txt 不得包含 extras：{bad_extras}"
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists(), "缺少 CI 配置"
    assert (ROOT / "SECURITY.md").exists(), "缺少安全说明"

    # 2. 参数校验失败返回可读中文，而不是 Pydantic 原始错误列表
    r = e.post("/auth/login", {}, expect=422)
    assert r.get("code") == 422 and "请求参数不合法" in str(r.get("detail", "")), r

    # 3. 未捕获异常不得把异常类型/消息回传客户端（原实现会泄漏）
    from app.main import unhandled_error
    secret = "SECRET_SQL_SELECT_password_FROM_users_42"
    fake_req = SimpleNamespace(method="GET", url=SimpleNamespace(path="/api/_probe"))
    # 这里会故意写一条带堆栈的服务端日志，测试期间静音以免污染回归输出
    log = logging.getLogger("hanpei")
    prev_level = log.level
    log.setLevel(logging.CRITICAL)
    try:
        resp = asyncio.run(unhandled_error(fake_req, RuntimeError(secret)))
    finally:
        log.setLevel(prev_level)
    body = resp.body.decode("utf-8")
    assert resp.status_code == 500, resp.status_code
    assert secret not in body and "RuntimeError" not in body, f"500 泄漏内部错误：{body}"
    assert "code" in body and "500" in body, body

    e.close()
    report("工程基建自测", e, "| 依赖锁定 / constraints extras / CI / 422 中文 / 500 不泄密")


if __name__ == "__main__":
    main()
