# Hanpei ERP — 汽车配件外贸 ERP

> 按《ERP系统规划方案.md》v2.1 与《核心数据结构设计.md》v2.1 **从零建成的可运行完整项目**（2026-11-23）。
> 业务主线：产品库 → 快速报价 → 销售订单 → 采购库存 → 出运单证 → 财务核算。
> 5 套端到端测试 + 全链路冒烟全绿；实现差异、业务口径、验收基线见规划方案**附录 E**，字段与表清单回写见数据结构设计**第 14 节**。

## 技术栈与部署形态

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12+ / FastAPI / SQLAlchemy 2 / Pydantic / Uvicorn / Alembic |
| 前端 | Vue 3 / Element Plus / Vite / Pinia / Vue Router / ECharts / Axios（Hash 路由） |
| 数据库 | 开发 SQLite（零配置，`data/erp.db`）；生产 PostgreSQL 16，`DATABASE_URL` 切换 |
| 单据 | ReportLab（QT/PI/PL PDF）、openpyxl（Excel 导入导出） |
| 部署 | **单端口**：后端直接托管 `frontend/dist`；生产 Docker Compose（PostgreSQL + Redis + MinIO + 后端 + Nginx） |
| 移动端 | PWA（manifest + Service Worker），可「添加到主屏幕」，替代规划中的桌面客户端 |

## 快速开始（本地，Windows / Linux 通用）

```bash
# 1) 后端依赖 + 初始化数据库（自动建表并灌入种子数据）
cd backend
python -m pip install -r requirements.txt
python seed.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8008

# 2) 前端构建（产物交给后端单端口托管）
cd ../frontend
npm install --registry https://registry.npmmirror.com
npm run build
```

浏览器打开 **http://127.0.0.1:8008**。

| 入口 | 账号 | 密码 |
|---|---|---|
| 内部系统 | `admin` | `admin123` |
| 客户门户（登录页切换） | `alnoor` | `portal123` |

首次启动会自动建 66 张业务表并初始化 7 个角色 / 8 个用户 / 6 个产品 / 3 个客户 / 仓库 / 汇率 / 收款账户。种子数据可用 `python seed.py` 重复执行（幂等）。

**前端热更新开发**：`cd frontend && npm run dev` → http://localhost:5173，`/api` 已代理到 `127.0.0.1:8008`。
开发机固定用 **8008**（避让 C-Lodop 打印插件占用的 8000）；生产 Docker 用 80/443。

## 环境变量

复制 `.env.example` 为 `.env` 后按现场修改；生产由 `deploy/install.sh` 自动生成随机值。

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | `sqlite:///./data/erp.db` 或 `postgresql+psycopg://user:pwd@host:5432/erp` |
| `SECRET_KEY` | JWT 签名密钥，**上生产必须替换** |
| `MASTER_KEY` | settings 敏感键 Fernet 加密主密钥；留空则首次启动自动生成到 `data/master.key` |
| `SERVE_FRONTEND` | `1` 时后端托管 `frontend/dist` |
| `BOOTSTRAP_ADMIN` / `BOOTSTRAP_PASSWORD` | 首次初始化的管理员账号 |
| `APP_PORT` | 默认 `8008` |

## 目录结构

```
backend/
  app/models/     9 个模型文件，66 张表（按域拆分）
  app/core/       权限矩阵、数据隔离、编号 CAS、审计、加密、通用 CRUD
  app/services/   库存移动加权、订单状态机、利润口径、PDF/Excel、自动催办
  app/api/        15 个路由模块（产品/CRM/报价/订单/采购库存/出运/财务/报表/系统/门户…）
  migrations/     Alembic 初始迁移 d3343c60b06a
  seed.py         种子数据
frontend/
  src/menu.js     RESOURCES + MENUS 单一配置源（驱动路由/列表/表单/菜单）
  src/components/ Pager.vue（全站统一分页）、ResourceList.vue（通用资源页）
  src/views/      工作台、报价编辑、订单详情、报表、系统参数、门户、登录
  public/         PWA manifest + Service Worker
deploy/           Dockerfile、docker-compose.yml、nginx.conf、install.sh、backup.sh、upgrade.sh
scripts/          5 套端到端测试 + smoke_api.py 全链路冒烟 + 测试公共封装
data/             运行期生成：erp.db、uploads/、backups/、master.key（已在 .gitignore）
```

## 功能实现状态

**核心业务链路全部打通并经过端到端测试**：

| 域 | 已实现 |
|---|---|
| 产品 | OE 归一化匹配（`25100-03011 → 2510003011`）、CRUD、Excel 批量导入/导出、图片 OE 匹配、水印模板、HS 编码/申报要素/退税率/底价/安全库存 |
| CRM | 客户、联系人、客户协议价、供应商、线索、跟进、客户 360、发帖记录 |
| 询报价 | 粘贴/Excel OE 三色匹配、自动带价（协议价优先）、折扣与审批、QT PDF、发送打点、转订单、F2 快速查价 |
| 销售订单 | 状态机自动流转、分批出运（数量上限校验）、PI PDF、状态日志、收款登记、业务员数据隔离 |
| 采购库存 | 采购建议、采购单、分批到货、采购退货、多仓库、移动加权成本、库存流水/批次、期初导入、盘点确认自动调账 |
| 出运单证 | 出运批次、分箱明细、拼柜建议、客户版 PL PDF、国内 PL 导入、单证清单 |
| 财务 | 收款核销（一收核多单）、付款审批、退款、汇率、退税、费用、利润核算 v1、提成（按已核销回款）、账龄、售后索赔、三方对账 |
| 系统 | 7 角色权限矩阵、成本字段脱敏、操作审计、站内通知、系统参数（敏感键加密）、功能开关、编号规则、备份 |
| 报表 | 工作台 KPI + 销售趋势、销售/产品/渠道/利润报表、漏斗、库存健康 |
| 客户门户 | `scope=portal` 令牌隔离，只读订单/单证/对账；门户令牌访问内部接口一律 403 |

**按 MVP 收敛原则保留为开关/占位（默认关闭，未做真实联调）**：素材库 API、SMTP/IMAP 实收发、OCR 图片询价、Maps/Facebook 自动采集、browser-use Agent、MCP Server 实体、Chrome 剪藏扩展、飞书推送。
**未做**：Electron/Tauri 桌面客户端（改由 PWA 替代）、阿拉伯语 RTL PDF（QT/PI/PL 为英文版式）、多语言 i18n、车型匹配。逐项原因见规划附录 E.4。

## 测试与验收

```bash
cd backend
python ../scripts/test_quote_flow.py        # 询报价闭环（16 次请求 / 2 份 PDF）
python ../scripts/test_order_flow.py        # 订单履约闭环（17 次请求 / 3 份 PDF）
python ../scripts/test_purchase_flow.py     # 采购库存闭环（11 次请求）
python ../scripts/test_finance_flow.py      # 财务闭环（19 次请求，含幂等/门户隔离）
python ../scripts/test_stocktake_return.py  # 盘点 / 采购退货闭环（16 次请求）
python ../scripts/smoke_api.py              # 全链路冒烟
python -m alembic upgrade head              # 空库迁移验证（生产 PG 前必跑）
```

测试用进程内 `TestClient`，无需起服务。实测结果：5 套全绿；冒烟覆盖 30 次真实 API 调用；真实 HTTP 服务上 `/api/health`、SPA 首页、登录、产品列表、静态资源全部 200；Alembic 空库建出 66 张业务表。

## 生产部署（Linux 一键）

```bash
cd deploy && sudo bash install.sh
```

脚本：检测 Docker → 生成随机 `.env`（权限 600）→ 构建镜像（多阶段构建前端 dist）→ 启动 PostgreSQL + Redis + MinIO + 后端 + Nginx → 健康检查 → 输出访问地址。
容器启动时先执行 `alembic upgrade head` 再拉起 uvicorn。
备份 `bash backup.sh`（`pg_dump` + 上传目录 tar，保留 30 天，可挂 cron）；升级 `bash upgrade.sh`（备份 → 重建 → 健康检查 → 失败回滚）。
人工三件事：域名解析、端口映射、防火墙放行 80/443。

## 上线前待办

> 已完成：Git 仓库初始化（分支 `main`）+ `v1.0.0` tag。以下为仍需人工/现场执行的事项。

1. 修改 `admin` 初始密码，`SECRET_KEY` / `MASTER_KEY` 纳入密钥管理；
2. 用真实产品/客户/期初库存 Excel 走一遍数据整理，核对 OE 准确率与报价匹配率；
3. 在 PostgreSQL 环境跑 `alembic upgrade head` + 5 套测试（当前实测在 SQLite）；
4. 逐项确认是否启用外部能力并完成素材库/邮件/飞书联调；
5. 补 UAT 用例与性能压测（产品搜索 < 1s、万行询价导入 < 30s、20 并发流畅）；
6. 做一次备份恢复演练，明确「系统为主、Excel 并行核对」的切换与回退条件。

完整清单见《ERP系统规划方案.md》附录 E.7。

## 文档索引

| 文件 | 作用 |
|---|---|
| `ERP系统规划方案.md` v2.1 | 14 模块功能规划、状态机、UI 规范、附录 E 实现差异与验收基线 |
| `核心数据结构设计.md` v2.1 | 数据字典、ER 图、权限模型，第 14 节为代码回写校准 |
| `素材库API开发指南（交底版）.md` | 素材库对接规范（`oe_norm` / `match-batch` / HMAC Webhook / 验收清单），ERP 侧开关待联调 |
| `README.md` | 本文件：安装、运行、测试、部署、验收 |
