# 素材库 API 开发指南（需求方：瀚沛汽配 ERP）

**版本**：v1.0 · **提出方**：瀚沛国际贸有限公司 ERP 项目组 · **面向**：素材库项目开发团队

> 本文是 ERP 系统对素材库 API 的**验收性要求**。素材库按本文实现后，ERP 产品中心将按 OE 号批量匹配并同步产品图片。
> 标注【必须】的条目是联调验收的硬性条件；【应该】为强烈建议；【可以】为可选增强。

---

## 0. 背景（一分钟了解我们要干什么）

我们是汽配外贸公司，产品**只认 OE 号**（无车型概念）。ERP 产品中心需要：
1. 上传/管理产品的图片（主图、细节图、包装图）；
2. **按 OE 号从素材库批量匹配图片**，一键同步到产品中心；
3. 素材库有新图/新打标时能**自动补图**到 ERP。

**你们的素材库现状**：同一个 OE 会有很多照片（源文件名各不相同，靠人工/规则打上 OE 标签），搜一个 OE 会返回该 OE 下全部照片。**这正是本设计要考虑的核心场景：一 OE 多图。**

---

## 1. 全局约定【必须】

| 项 | 要求 |
|---|---|
| **OE 归一化** | 所有 OE 匹配必须按归一化值（字段名 `oe_norm`）进行。规则：**去掉空格、连字符 `-`、下划线 `_`，转大写**。例：`25100-03011` → `2510003011`；`25100 03011` → `2510003011`。接口同时返回 `oe_raw`（原始写法）与 `oe_norm` |
| 认证 | `X-API-Key: <key>`；key 分**只读 key** 和**读写 key** 两种，可吊销 |
| 版本 | 路径前缀 `/v1`；只增字段不改不删；破坏性变更走 `/v2` |
| 时间 | ISO 8601 UTC（`2026-11-21T07:21:00Z`） |
| 分页 | cursor 分页：`?limit=50&cursor=xxx`，响应 `{ "items": [...], "next_cursor": "..." }`；limit 上限 200 |
| 幂等 | 所有创建类 POST 支持 `Idempotency-Key` 请求头，重试不产生重复数据【必须】 |
| 限流 | 120 req/min/key，超限返回 429 + `Retry-After` |
| 统一错误体 | `{"error": {"code": "OE_NOT_FOUND", "message": "…", "request_id": "…"}}` |

---

## 2. 数据模型【必须】

### 2.1 Asset（素材）

```json
{
  "id": "ast_8f3k2j",
  "type": "image",
  "filename": "25100-03011_主图.jpg",
  "url": "https://cdn.your-domain.com/a/ast_8f3k2j.jpg",
  "thumb_url": "https://cdn.your-domain.com/a/ast_8f3k2j_400.webp",
  "width": 2000,
  "height": 2000,
  "size": 483920,
  "format": "jpg",
  "sha256": "9c2a…",
  "role": "main",
  "is_primary": true,
  "source": "photography",
  "license": "self",
  "oes": [
    { "oe_raw": "25100-03011", "oe_norm": "2510003011" }
  ],
  "product_codes": ["HP-0001"],
  "tags": ["水泵", "白底"],
  "status": "available",
  "created_at": "2026-11-21T07:00:00Z",
  "updated_at": "2026-11-21T07:00:00Z"
}
```

字段要求：

| 字段 | 级别 | 说明 |
|---|---|---|
| `oes[]`（含 oe_raw + oe_norm） | 【必须】 | 一图可挂多个 OE；归一化规则见第 1 节 |
| `role` | 【必须】 | 枚举：`main` 主图 / `detail` 细节 / `packaging` 包装 / `label` 标签面 / `scene` 场景；**缺省 `detail`**。这是"一 OE 多图"场景下 ERP 挑图的依据 |
| `is_primary` | 【必须】 | 该图是否为其 OE 下的主图（与 role=main 一致使用；无 role 时的兜底） |
| `url` / `thumb_url` | 【必须】 | CDN 直链；thumb 为 400px 宽档 |
| `sha256` | 【必须】 | 文件去重键，同文件重复上传返回 409 + 已存在 id |
| `source` | 【必须】 | `photography` 实拍 / `official` 官方图 / `scrape` 网络采集 / `clipper` 剪藏 / `customer` 客户提供 |
| `license` | 【必须】 | `self` 自有 / `supplier` 供应商 / `web` 网络 / `unknown` 未知。**ERP 只自动同步 self/supplier，web/unknown 需人工确认**（防侵权） |
| `product_codes[]` | 【应该】 | 素材侧可选维护 ERP 产品编码，命中时匹配最快 |
| `tags` / `status` | 【可以】 | 标签字典建议单独 `/v1/tags` 维护 |

**打标来源留痕**【应该】：`tag_source`：`manual` / `filename` / `excel` / `api`——图多了以后标签错误需要可追溯。

### 2.2 一 OE 多图约定【必须】

同一 OE 挂几十张照片是常态。要求：

1. **匹配接口返回数组**（不是单图），并带 `total_matched`（该 OE 全部命中数，不受 limit 截断影响）；
2. **服务端排序规则固定**（ERP 照单全收，不自己排序）：
   1. `role`：main > detail > packaging > label > scene
   2. `is_primary` = true 优先
   3. `source`：photography > official > clipper > scrape > customer
   4. 分辨率/文件质量分降序
   5. `updated_at` 新者优先
   6. **tie-breaker：`id` 升序**（保证同一参数两次请求顺序完全一致——产品图不能今天一个样明天一个样）【必须】
3. 支持 `roles=main,detail` 过滤参数【必须】；
4. 近似重复图（同角度连拍）暂不做自动去重【可以】（P2 阶段考虑 pHash 相似去重）。

---

## 3. 接口清单

### 3.1 匹配类（ERP 产品中心的主链路）⭐【必须】

#### `GET /v1/assets/match?oe=25100-03011&limit=10&roles=main,detail`

单 OE 匹配。**OE 无命中时返回 200 + `matched:false`，不要 404**（批量场景不能因个别未命中整单报错）。

响应：

```json
{
  "oe_raw": "25100-03011",
  "oe_norm": "2510003011",
  "matched": true,
  "total_matched": 47,
  "assets": [
    {
      "id": "ast_8f3k2j",
      "url": "https://cdn.…/ast_8f3k2j.jpg",
      "thumb_url": "https://cdn.…/ast_8f3k2j_400.webp",
      "role": "main",
      "is_primary": true,
      "width": 2000, "height": 2000,
      "source": "photography",
      "license": "self"
    }
  ]
}
```

#### `POST /v1/assets/match-batch`【必须 · 优先级最高】

ERP 同步图片一律走批量接口（一次整页产品，不逐个查）。单次 ≥ 50 项、P95 < 500ms。

请求：

```json
{
  "items": [
    { "key": "oe", "value": "25100-03011" },
    { "key": "oe", "value": "22441 03050" },
    { "key": "product_code", "value": "HP-0001" }
  ],
  "limit_per_item": 6,
  "roles": ["main", "detail"],
  "thumb_width": 400
}
```

响应：

```json
{
  "results": [
    {
      "key": "oe", "value": "25100-03011",
      "oe_norm": "2510003011",
      "matched": true,
      "total_matched": 47,
      "assets": [ "…同上结构，最多 limit_per_item 张，已按排序规则排好…" ]
    },
    { "key": "oe", "value": "22441 03050", "oe_norm": "2244103050",
      "matched": false, "total_matched": 0, "assets": [] }
  ]
}
```

> 注意：**单项未命中不影响整批**（matched:false），个别项格式非法返回该项 `error` 字段而非整体 400。

#### `GET /v1/assets/by-product/{product_code}`【应该】

素材库已用 `product_codes` 建档时的快速通道，结构同 match。

### 3.2 素材 CRUD 与检索【必须】

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/v1/assets` | 检索：`?oe=` / `?product_code=` / `?tag=` / `?source=` / `?role=` / `?q=`（文件名/标签）/ `?updated_since=`（增量）/ cursor 分页 |
| `GET` | `/v1/assets/{id}` | 详情（含全部 oes、tags） |
| `POST` | `/v1/assets` | 上传：multipart 文件；或 `{"import_url": "https://…"}` 网络图导入【应该】 |
| `PATCH` | `/v1/assets/{id}` | 改 `role` / `is_primary` / `tags` / `source` / `license` / `status` |
| `DELETE` | `/v1/assets/{id}` | 软删（status=archived）；彻底删除另设 `purge`【应该】 |
| `POST` | `/v1/assets/{id}/oes` | 追加 OE 标签 `{"oes": ["25100-03011"]}`（服务端归一化） |
| `DELETE` | `/v1/assets/{id}/oes/{oe_norm}` | 解绑 OE |
| `POST` | `/v1/assets/{id}/primary` | 设为主图：`{"oe_norm": "2510003011"}`（同 OE 下原主图自动取消） |

### 3.3 同步机制【P1 必须 · P0 可后置】

**Webhook 推送为主 + 增量拉取兜底。**

`POST /v1/webhooks` 订阅：

```json
{
  "url": "https://erp.our-domain.com/api/asset/sync-hook",
  "secret": "shared-secret-for-hmac",
  "events": ["asset.created", "asset.updated", "asset.oe_added", "asset.archived"]
}
```

推送体：

```json
{
  "event_id": "evt_…",
  "event": "asset.oe_added",
  "at": "2026-11-21T07:21:00Z",
  "asset": { "id": "ast_8f3k2j", "oes": [{"oe_norm": "2510003011"}], "role": "detail", "thumb_url": "…", "url": "…" }
}
```

要求：
- 签名：`X-Signature = HMAC-SHA256(body, secret)`，带 `X-Timestamp`（±5 分钟防重放）【必须】；
- 重试：指数退避 5 次（1m/5m/30m/2h/6h），消费方按 `event_id` 幂等【必须】；
- 兜底：`GET /v1/events?since=<时间>&cursor=` 事件流，保留 30 天【应该】。

### 3.4 图片交付【必须】

- CDN 直链 + 尺寸变换参数：`?w=400&f=webp`（400 / 1200 / 原图三档）；
- 链接长期有效（供 ERP 镜像缓存）【必须】；防盗链用签名 URL 属【可以】（若启用，签名有效期 ≥ 24h 并提供续签接口）；
- 备用下载：`GET /v1/assets/{id}/download`（`Content-Disposition`）【应该】。

---

## 4. 安全与合规【必须】

1. API Key 分环境（prod/test）、分权限（只读/读写）、可吊销；
2. Webhook HMAC 签名 + 时间戳防重放；
3. `license` 字段必填——这是我们的**法务红线**，网络来源图不能混进自动同步；
4. 审计：素材的创建/打标/改 role/软删留操作日志，提供 `GET /v1/audit` 查询【应该】。

## 5. 错误码【必须】

| code | HTTP | 含义 |
|---|---|---|
| `INVALID_OE` | 400 | OE 无法归一化（空/非法字符） |
| `OE_NOT_FOUND` | 404 | 仅用于单资源按 OE 精查的语义场景；match 接口用 matched:false |
| `DUPLICATE_ASSET` | 409 | sha256 已存在（响应带已存在 id） |
| `RATE_LIMITED` | 429 | 见 Retry-After |
| `WEBHOOK_SIGNATURE_INVALID` | 401 | 签名/时间戳校验失败 |

## 6. 交付里程碑

| 期 | 交付内容 | 联调对象 |
|---|---|---|
| **P0** | 数据模型 + CRUD + `match`/`match-batch` + CDN 链接 | ERP 产品中心"从素材库匹配图片"按钮 |
| **P1** | Webhook + events 增量 + 签名 + audit | ERP 自动补图 + 系统管理对接配置 |
| **P2** | pHash 相似去重 / 视频素材 / OE Excel 批量打标 | 报价单配图、发帖记录关联 |

## 7. 验收清单（我们将按此逐条测试）

- [ ] `POST /v1/assets/match-batch` 50 个 OE P95 < 500ms；
- [ ] 归一化互认：`25100-03011` / `25100 03011` / `2510003011` 三种写法命中同一素材；
- [ ] **一 OE 多图**：单 OE 挂 50 张 → `total_matched=50`、limit_per_item 截断正确、role/主图排序正确；
- [ ] **排序稳定**：同参数连续两次请求顺序逐张一致（tie-breaker 生效）；
- [ ] 批量中混入未命中项/非法 OE → 整批 200，逐项标记 matched:false / error；
- [ ] 幂等：同 `Idempotency-Key` 重试不产生重复素材；
- [ ] Webhook 断连恢复后能靠 `GET /v1/events` 补齐；
- [ ] `license=web` 的素材不出现在默认自动同步结果中（或带显著标记）。

## 8. 联调方式

- 先提供 **mock 环境**（test key）+ OpenAPI（Swagger）文档；
- ERP 侧对接人提供：回调地址、IP 白名单、共享密钥；
- 定稿前请把 OpenAPI 文档发 ERP 项目组**预审**，避免联调期改契约。

---
*OE 归一化参考实现：ERP 侧 `backend/app/core/normalize.py` 的 `normalize_oe()`（去 `[\s\-_]`、upper）。如需我方提供参考代码/测试用例集，联系 ERP 项目组。*
