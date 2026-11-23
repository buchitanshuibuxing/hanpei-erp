# 变更记录

本项目从零落地后的版本记录。业务设计口径见《ERP系统规划方案.md》附录 E，数据口径见《核心数据结构设计.md》第 14 节。

## v1.0.4（2026-11-23）—— GitHub 托管、一键部署与真实 Linux 实测

- **代码托管**：创建公开仓库 `github.com/buchitanshuibuxing/hanpei-erp`，推送 `main` 与 `v1.0.0` ~ `v1.0.3` 全部 tag，保留完整提交历史。
- **一键部署脚本**：新增 `deploy/onekey.sh`，双模式：`lite`（默认，系统 Python 3.12 + SQLite + 前端构建 + systemd，端口 8008）与 `--docker`（Docker Compose 起 PG / Redis / 后端 / Nginx，端口 80；MinIO 改为可选 profile）。8 步幂等流程、随机密钥、健康检查覆盖 health / SPA / 管理员登录；apt / pip / npm / Docker 全走国内镜像；`git clone` 被 TLS 干扰时自动回落 GitHub codeload tarball。
- **真实 Linux 部署实测抓到并修复 4 类本地与 CI 都漏掉的问题**：
  1. `backend/constraints.txt` 的 `psycopg[binary]==3.3.9` 违反 pip 新 resolver「constraints 不得带 extras」，`pip install -c` 直接报错；改为纯包名并补锁 `psycopg-binary` / `pydantic-core`，加静态防护断言。
  2. `.env` 的 SQLite 相对路径在 systemd `WorkingDirectory=backend/` 下解析到不存在的目录，启动报 `unable to open database file`；改为绝对路径并让旧 `.env` 自动迁移。
  3. `backend/seed.py` 硬编码 `admin123`，未读 `.env` 的 `BOOTSTRAP_PASSWORD`，一键脚本打印的随机密码是假的、登录必然 401；改为读取 `BOOTSTRAP_ADMIN / BOOTSTRAP_PASSWORD / BOOTSTRAP_PORTAL_USER / BOOTSTRAP_PORTAL_PASSWORD`（不设时保留开发默认值），加防护断言。
  4. 国内镜像加速源对 `minio/*` 一律 denied，而后端代码无任何 S3 / MinIO 依赖（附件落 `data/uploads/`）；`docker-compose.yml` 固定版本标签并加 `profiles: ["storage"]` 默认不启动；同时修 `deploy/install.sh` 从 `deploy/` 读不到根 `.env` 导致 `${PG_PASSWORD:?}` 拒绝启动的问题（补软链）、初始密码改随机并打印；脚本更新失败时不再静默沿用旧代码，改为 codeload tarball 覆盖。
- `SECURITY.md` 补充：种子账号仅首次初始化生效、随机凭据来源、`.env` 权限 600。
- **VM 实测结论**：PVE VMID 108（Ubuntu 22.04.5 / 10.10.20.150）上，lite 与 `--docker` 两种形态均 health / SPA 200、随机密码登录拿到 token；PG 容器内 Alembic 跑完两段迁移，库内 68 张表、8 个种子用户、转单唯一索引齐全。逐项见规划附录 E.11 与 README「部署实测记录」。

## v1.0.3（2026-11-23）—— 工程稳健性加固

对标 GitHub 同类开源 ERP（Carbon / ERPNext / AureusERP / IDURAR）后的工程层补齐，**未改动业务逻辑**：

- **修复生产启动缺陷**：`backend/requirements.txt` 补上缺失的 `alembic`（Docker 启动命令依赖它，原镜像会 `No module named alembic`）。
- **依赖锁定**：新增 `backend/constraints.txt`（14 个精确版本），`deploy/Dockerfile` 改为 `pip install -r requirements.txt -c constraints.txt`；前端 CI 改用 `npm ci` 按 lock 还原。
- **CI**：新增 `.github/workflows/ci.yml`，Python 3.12/3.13 双矩阵跑 ruff + 8 套测试 + 冒烟 + Alembic 空库迁移（断言 67 业务表与 head），前端独立构建 job。
- **一键回归**：新增 `scripts/run_all.py`，CI 与人工共用同一入口。
- **Lint**：新增根目录 `pyproject.toml`（ruff `E4/E7/E9/F`，忽略与项目刻意写法冲突的规则）；本地实跑全过，并修掉 3 处未使用变量、2 处歧义变量名。
- **修测试自身缺陷**：`test_purchase_flow.py` 原依赖 `/stock-balances` 默认分页（`size=10`），数据量增长后第二次全量回归会 `StopIteration`；改为按 `product_id / warehouse_id / ref_id` 显式过滤 + `size=100`，连续两次全量回归全绿。
- **可观测性与异常安全**：`app/main.py` 加结构化日志、访问日志中间件（不读 body，不影响幂等中间件）、`RequestValidationError` 中文 422、**未捕获异常不再把异常类型与消息回传客户端**（原实现会泄漏内部信息），改记服务端日志并返回通用 500。
- **文档**：新增 `SECURITY.md`（认证/密钥/已知边界）、本文件；新增 `scripts/test_engineering_guards.py` 自测依赖锁定、CI 存在、422 中文、500 不泄密。
- 版本接口 `/api/system/version` 同步为 `1.0.3`。

## v1.0.2（2026-11-23）—— 附录 E.8 四项边界收口

- PL 导入单批数量上限 + `_sync_shipped()` 以 `ShipmentItem` 为事实源重算（重导入替换而非累加）。
- `sales_orders.quotation_id` 唯一索引（模型 + 迁移 `b7e2c4a91f30` + 启动引导），转单并发兜底。
- 门户确认落库 `portal_confirmations`，内部可查，不改写订单状态/金额。
- 子资源写接口 `check_parent_owner()` 按父记录显式归属校验。
- 新增 `scripts/test_v102_boundaries.py`；详见规划附录 E.9。

## v1.0.1（2026-11-23）—— 满屏布局 + 全链路闭环加固

- 右侧内容区满屏自适应（`min-width` 弹性列）；通用列表按钮白名单消除死链。
- 核销上限、审批闭环、出运扣库存与释放占用、状态机异常、导出隔离、主数据删除保护等修复。
- 新增 `scripts/test_closure_fixes.py`；详见规划附录 E.8。

## v1.0.0（2026-11-23）—— 从零建成完整项目

- 后端 66 张业务表 / 15 个 API 模块 / Alembic 初始迁移 / 种子数据；前端 Vue 3 全菜单 + PWA；Docker Compose 部署与备份升级脚本；5 套端到端测试 + 30 步冒烟。
- 详见规划附录 E 与 README。
