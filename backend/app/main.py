"""Hanpei ERP 应用入口。

- 单端口：后端同时提供 /api 与前端整站（frontend/dist 存在时自动托管）
- 幂等中间件：写接口带 Idempotency-Key 时防止双击/重试重复建单
- APScheduler：每小时自动催办
"""
import json
import os
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core.deps import require
from .db import ROOT, SessionLocal, engine, init_db
from .models.system import IdempotencyKey, User

sys.path.insert(0, str(ROOT / "backend"))

_scheduler = None


def _ensure_indexes():
    """对 create_all 建出来的老库补齐唯一索引（新库由模型 __table_args__ 自带）。

    生产走 Alembic 迁移；这里是开发/单机 SQLite 模式的幂等校准，SQL 在 PG/SQLite 均可用。
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_orders_quotation_id "
                              "ON sales_orders (quotation_id)"))
        except Exception as exc:
            print(f"[warn] 唯一索引 uq_sales_orders_quotation_id 未创建（可能存在重复报价引用）：{exc}")


def _bootstrap():
    init_db()
    _ensure_indexes()
    with SessionLocal() as db:
        if db.query(User).count() == 0:
            import seed
            seed.run()
    # 期初数据 / 种子数据写入后校准编号序列，避免 C0001、HP-0001 之类撞号
    from .core.numbering import reconcile_sequences
    reconcile_sequences()


@asynccontextmanager
async def lifespan(_app):
    global _scheduler
    _bootstrap()
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from .services.reminders import check_reminders
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        _scheduler.add_job(check_reminders, "interval", hours=1, id="reminders",
                           replace_existing=True, max_instances=1)
        _scheduler.start()
    except Exception as exc:
        print(f"[warn] scheduler disabled: {exc}")
    yield
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


app = FastAPI(title="Hanpei ERP API", version="1.0.0", lifespan=lifespan,
              description="汽车配件外贸 ERP：产品→报价→订单→履约→利润核算")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def idempotency(request: Request, call_next):
    """P0 补充：写接口幂等；相同 key 直接返回首次结果。"""
    key = request.headers.get("Idempotency-Key")
    if not key or request.method not in ("POST", "PUT", "PATCH", "DELETE") \
            or not request.url.path.startswith("/api/"):
        return await call_next(request)
    with SessionLocal() as db:
        hit = db.query(IdempotencyKey).filter_by(idempotency_key=key).first()
        if hit:
            return JSONResponse(content=hit.response_json or {"message": "重复请求已忽略"},
                                status_code=200)
    response = await call_next(request)
    chunks = b""
    async for chunk in response.body_iterator:
        chunks += chunk
    if response.status_code < 400:
        try:
            payload = json.loads(chunks.decode("utf-8"))
        except Exception:
            payload = {"message": "ok"}
        with SessionLocal() as db:
            try:
                db.add(IdempotencyKey(idempotency_key=key, endpoint=request.url.path,
                                      user_name="", response_json=payload,
                                      created_at=datetime.utcnow()))
                db.commit()
            except Exception:
                db.rollback()
    content_type = (response.headers.get("content-type") or response.media_type
                    or "application/octet-stream").split(";")[0].strip()
    headers = {k: v for k, v in response.headers.items()
               if k.lower() not in ("content-length", "content-type")}
    return Response(content=chunks, status_code=response.status_code,
                    headers=headers, media_type=content_type)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": str(exc.detail), "code": exc.status_code})


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={
        "detail": f"服务端处理失败：{type(exc).__name__}: {exc}", "code": 500})


from .api import (auth, common, crm, extended, finance, orders,  # noqa: E402
                  products, purchase_inventory, quotations, reports,
                  shipping, system)

for module in (auth, common, crm, extended, finance, orders, products,
               purchase_inventory, quotations, reports, shipping, system):
    app.include_router(module.router)


@app.post("/api/system/reminders/run")
def run_reminders(_=Depends(require("system", "edit"))):
    from .services.reminders import check_reminders
    return {"created": check_reminders(manual=True)}


@app.get("/api/system/version")
def version():
    return {"version": "1.0.0", "database": "sqlite" if "sqlite" in str(
        os.getenv("DATABASE_URL", "") or "sqlite") else "postgresql",
        "features": "MVP full-chain"}


FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.exists() and os.getenv("SERVE_FRONTEND", "1") == "1":
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "接口不存在")
        target = (FRONTEND_DIST / full_path).resolve()
        if FRONTEND_DIST.resolve() in target.parents and target.is_file():
            return FileResponse(target)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "前端尚未构建，请先执行 npm run build")
