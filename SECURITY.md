# 安全说明

## 认证与隔离

- 内部账号与门户账号使用**两套独立 JWT scope**（`internal` / `portal`）。门户令牌访问任何内部接口一律 403；`/api/portal/*` 强制按 `customer_id` 过滤，越权订单返回 404。
- 登录失败 **5 次锁定 15 分钟**（内部与门户各自计数，见 `app/api/auth.py` 与 `login_attempts` 表），密码用 PBKDF2-SHA256（180,000 轮）加盐存储。
- 角色 × 模块 × 动作权限矩阵以 `app/core/permissions.py` 为唯一事实源；业务员按 `owner_name` 隔离，成本/毛利/底价等字段由 `mask()` 脱敏。

## 密钥与配置

- `SECRET_KEY`：`.env.example` 里 `CHANGE_ME_TO_A_LONG_RANDOM_STRING` 是**占位符**，`get_secret()` 检测到该值会自动改用 `data/secret.key` 中的随机密钥；上生产必须替换为强随机值并纳入密钥管理。
- `MASTER_KEY`：settings 中 9 类敏感键（邮箱密码、API Key、Webhook 等）用 Fernet 加密，列表接口回显 `******`，审计日志不落明文。
- `data/`（数据库、密钥、上传、备份）已在 `.gitignore` 中排除；`deploy/install.sh` 会生成权限 600 的 `.env`。

## 已实现的防护

- 写接口 `Idempotency-Key` 幂等、编号 `sequences.version` CAS、库存 `stock_balances.version` 乐观锁、报价转单唯一索引。
- 所有业务写操作写 `audit_logs`；关键单据状态流转写 `status_logs`；被引用的主数据禁止直接删除。
- 未捕获异常统一返回**通用 500 文案**，堆栈只写服务端日志，不回传客户端（见 `app/main.py`）。

## 已知边界（上线前须确认）

| 项 | 现状 | 建议 |
|---|---|---|
| CORS | `allow_origins=["*"]`（`allow_credentials=False`） | 单端口同源部署可用；公网独立部署时改为白名单域名 |
| API 级限流 | 暂无通用限流，仅登录失败锁定 | 公网暴露时加网关层限流 / `express-rate-limit` 类中间件 |
| 传输加密 | 容器内 HTTP，由 Nginx 终结 TLS | 生产必须配 80/443 证书，禁止明文对外 |
| 上传文件 | 落 `data/uploads/`，按扩展名保存 | 公网开放前补 MIME/大小校验与病毒扫描 |
| 数据库 | 开发 SQLite 实测；生产 PostgreSQL 16 | 上线前在 PG 跑迁移 + 全量回归（规划附录 E.7） |
| 默认账号 | `admin/admin123`、门户 `alnoor/portal123` | **上生产第一件事就是改掉** |

## 报告安全问题

本项目为内部自用系统，未设立公开漏洞赏金计划。发现安全问题请直接联系仓库维护者，不要在公开 Issue 中贴出密钥、令牌或可复现的攻击载荷。
