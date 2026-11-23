# 变更记录

本项目从零落地后的版本记录。业务设计口径见《ERP系统规划方案.md》附录 E，数据口径见《核心数据结构设计.md》第 14 节。

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
