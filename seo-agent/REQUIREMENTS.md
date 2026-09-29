# AI SEO Agent — 产品需求与设计规划书

版本：v0.1（初稿）
日期：2026-09-29
状态：待评审 → 确认后进入技术方案与排期

---

## 0. 一句话定义

**一个"会自己动手"的网站 SEO 智能体**：接入站点后，自动完成技术体检 → 关键词与竞品分析 → 内容规划 → 逐页产出优化建议/改写稿 → 持续监测排名与流量 → 用可追溯的证据告诉用户"下一步该做什么、为什么"。

与现有 SEO 工具（Screaming Frog / Ahrefs / Semrush）的根本区别：
- 它们是**数据仪表盘**，告诉你现状，不动手。
- 本产品是**执行型 Agent**，从诊断直接跑到"改写好的标题、Meta、内链结构、Schema、Sitemap、robots.txt 修复包"，并可托管定时复扫。

---

## 1. 目标与成功指标

### 1.1 目标用户（Persona）

| 角色 | 痛点 | 核心诉求 |
|---|---|---|
| **P1 独立站/中小电商站长**（主） | 不会 SEO、没预算请顾问、看不懂英文报告 | 全托管，一键体检 + 每月行动清单 + 自动改写商品页 |
| **P2 增长/内容团队（5–50 人）** | 内容产能瓶颈，关键词与内容脱节 | 批量内容 Brief、SERP 差距分析、内容日历 |
| **P3 SEO 从业者/代理商** | 多站点管理、交付效率低 | 批量站点、white-label 报告、客户看板 |
| **P4 开发者** | 需要可编程的 SEO 数据 | REST/GraphQL API、Webhook、MCP Server |

### 1.2 北极星指标

- **被采纳的建议数 / 周**（用户实际执行或一键应用的优化条数）
- 辅助指标：站点接入转化率、扫描成功率、建议可执行率（人工抽检 ≥70%）、周留存

---

## 2. 功能需求

### 2.1 P0 —— MVP 必须有（4–6 周）

#### F1 站点接入与数据层
- 接入方式：`sitemap.xml` / GSC（Google Search Console）/ GA4 / 权重 API（DataForSEO、Semrush、Ahrefs API 三选一接口抽象）/ 直接 URL 抓取
- 站点地图可视化：URL 树、层级深度、孤岛页面、孤儿页、软 404、重定向链/环
- 抓取器：robots.txt 解析（allow/disallow + 抓取延迟）、sitemap 分片、断点续抓、并发控制
- 站点指纹：技术栈识别（WordPress/Shopify/Next.js 等），决定后续建议模板

#### F2 技术 SEO 体检（规则包可插拔，60+ 检查项起）
分模块打勾式输出，每项给出**证据 + 影响 + 修复建议**。检查项按生态分包，新增市场不改核心代码。
- **【通用】抓取与索引**：robots 误封、Sitemap 缺失/过期、noindex 误用、canonical 缺失/冲突、软 404、参数重复、HTTP 状态异常
- **【通用】信息架构**：层级 >3、面包屑缺失、内部孤岛、孤儿页、URL 结构、重复内容（近似度）
- **【通用】页面级**：Title 缺失/重复/超长、Meta description、H1 唯一性、图片 alt、渲染（JS）依赖内容的比例
- **【通用】性能与体验**：LCP/CLS/INP 代理指标、TTFB、图片格式与尺寸、字体加载、移动端适配
- **【通用】结构化数据**：Schema.org 缺失/类型错误/字段不完整
- **【通用】安全与信任**：HTTPS、混合内容、证书过期
- **【Google 包】** ：Search Console 覆盖率与实际抓取差异、移动优先索引、Core Web Vitals 实地数据对比、hreflang 与多语言正确性、富媒体结果资格、广告/购物等专用标记、Sitemaps 分类拆分
- **【百度包】**：百度搜索资源平台收录率与站点属性校验、robots 中 Baiduspider 单独策略、ICP 备案与站点验证、移动适配（需要极速落地页规范）、中文分词下的标题长度与语义完整性、站内搜索与落地页关系、外链权重传递结构
- **【中文生态扩展包】**：微信搜一搜收录与内容开放、知乎/小红书等站外内容的引用与导流、微信公众号文章与官网互链、品牌实体信息一致性（NAP）

#### F3 关键词与内容规划
> **多市场处理**：每个站点声明 `market`（`google` / `baidu` / `both`）。关键词库、SERP 抓取、内容规则全部按市场路由——Google 与百度的 SERP 结构、意图分类标准、字数偏好差异很大，**绝不能混用同一份数据**。双语站按语言+市场建立独立子域/目录的跟踪视图。
- 关键词聚类（从 SERP 共现、意图分类：信息/导航/商业/交易）
- 意图-页面类型映射（意图"对比"→需要对比页；意图"价格"→需要价格/产品页）
- **内容缺口分析**：竞品排名页的主题覆盖 vs 我方覆盖
- **中英文差异处理**：中文按语义单元与字数（15-30 字标题最佳）而非字符数；英文按像素宽度（50-60 字符）并处理截断
- 输出**内容日历**：URL / 目标词 / 意图 / 类型 / 建议字数 / 差异化角度 / 内链机会 / 目标市场

#### F4 AI 内容 Brief + 改写
- 一键生成 Brief：目标关键词、搜索意图、必需实体、Top10 共同点、差异化机会、字数区间、标题候选、FAQ 候选
- 单页改写：Title / Meta / H1-H3 结构 / 正文扩写 / FAQ / CTA
- **反 AI 味**（用 humanizer 思路约束）：禁套话、禁"在当今数字化时代"、变量化表达、句长波动

#### F5 报告与行动清单
- 站点健康分（0–100，分模块加权）
- P0/P1/P2 优先级行动清单，每条含：问题、证据 URL、预估影响、实现难度、建议改法（可复制代码）
- **一键导出**：Markdown / PDF / Excel / 直接生成可提交的 PR diff

### 2.2 P1 —— 第二个迭代（+4 周）

- **SERP 排名与流量监测**：日级排名、CTR、曝光、点击、页面级变化；异常告警（跌幅 >20%）
- **竞品追踪**：自动识别真实竞品（按 SERP 重合度而非关键词重叠），竞品新增/消失页面
- **内链自动规划**：中心页 → 长尾页的锚文本与落位建议，一键生成内部链接矩阵
- **Schema 自动生成与校验**：按页面类型生成 JSON-LD，含 Google 富媒体结果测试
- **GEO / AI 搜索优化**（差异化重点）：针对 AI 答案引擎（AEO）的可引用性优化——实体一致性、问答块、事实密度、结构化数据、来源可验证性；输出"能否被 AI 引用"的评估
- **定时任务 + 变更回滚**

### 2.3 P2 —— 商业化（+6 周）

- 多站点 / 团队协作 / 角色权限
- White-label 报告（换品牌、去白标）
- 关键词库 + 内容生成额度计费
- **MCP Server**：把本产品能力暴露给 AI 编码助手（Claude Code / Codex），让 Agent 能在用户项目里直接改代码
- Slack / 飞书 / 企业微信 通知
- WordPress / Shopify / Webflow / Next.js 插件与 API

---

## 3. Agent 架构设计（核心）

### 3.1 设计原则
1. **证据优先**：任何结论必须能追到具体 URL + 抓取到的内容片段，禁止"我觉得"
2. **可回滚**：所有写操作产出 diff/PR，不直接改生产
3. **人在环**：高风险动作（改 robots、批量重定向、删页）需确认
4. **成本可控**：分层模型 + 缓存 + 批处理

### 3.2 多 Agent 分工

```
Orchestrator（任务编排器）
├── Crawl Agent      站点抓取 / 渲染 / 资源探测
├── Tech Audit Agent 60+ 检查项执行，产出 Finding
├── Keyword Agent    关键词扩展、聚类、意图分类
├── SERP Agent       Top10 抓取、结构拆解、共性/差异分析
├── Content Agent    Brief 生成、页面改写
├── Prioritizer      影响 × 难度 排序，生成行动计划
└── Reporter         报告/周报/告警生成
```

每个 Agent 的输出都是**结构化 JSON Schema**，下游 Agent 只消费 JSON，不读自然语言（避免幻觉传导）。

### 3.3 关键技术点
- **抓取**：Playwright 做 JS 渲染对比原始 HTML（识别"SEO cloaking 风险"和渲染不一致）
- **规模**：单站 10 万 URL 级别，分片 + 断点续跑 + 优先级队列（重要页先抓）
- **模型分层**：
  - 便宜层：分类、意图打标、去重、批量聚类
  - 强模型：Brief 质量、页面改写、策略建议
  - 本地/规则层：60+ 技术检查（纯规则，不用 LLM，省钱且稳定）
- **成本控制**：内容 hash 缓存、页面级增量更新、失败重试退避
- **评测**：黄金样本集（100 个标注页面）做回归，防止改 Prompt 掉点

---

## 4. 技术栈

### 4.1 选型原则
自托管友好、成本可控、后续可商业化、**开发速度优先**（本项目 40% 复杂度在 LLM 编排、25% 在文本/HTML 解析，Python 生态优势决定性）。

> **语言选型评估记录（曾评估 Go 1.27，结论不采用）**
> - Go 的真实优势是爬虫并发与部署轻量，但本项目实际量级是单站 1w~10w URL、每日数次扫描，`asyncio + httpx` 完全承载，并发优势**兑现不了**。
> - 真正的大头是 LLM 编排（~40%）：Python 有 instructor / litellm / langchain，Go 只能手写多 provider 适配与结构化输出校验，损失是**真实且高频的**。
> - SEO 检查（~25%）依赖 trafilatura / extruct / lxml，Go 无成熟等价物；Schema.org 抽取要自己手写 JSON-LD + Microdata + RDFa 三套解析（纯苦活）。
> - 代价：约 20~30% 开发速度损失。不采纳。
> - Go 仍可在项目外单独学习，不与产品技术选型绑定。

### 4.2 推荐栈

| 层 | 选型 | 理由 |
|---|---|---|
| **后端语言** | **Python 3.12** | 项目 40% 复杂度在 LLM 编排、25% 在文本/HTML 解析，Python 在这两块生态优势决定性；异步抓取在本项目量级完全够用 |
| **后端框架** | **FastAPI** + Uvicorn | Pydantic 原生集成，类型贯穿 API/DB/LLM 输出；自动 OpenAPI 文档；异步原生 |
| **数据访问** | **Pydantic v2** + **SQLAlchemy 2.0 (async)** + **Alembic** | Pydantic 模型同时用于 API 校验、DB 序列化、LLM 结构化输出，一份定义三处用 |
| **数据库** | PostgreSQL 16（主） + TimescaleDB（排名时序）+ pgvector（相似页聚类） | 一套三种扩展，避免多库运维 |
| **迁移** | **Alembic** | autogenerate + 版本化，可回滚可审计 |
| **爬虫 HTTP** | **httpx** (async) + `urllib.robotparser` | httpx 支持 HTTP/2 与连接池；robots 用标准库解析器 |
| **HTML 解析** | **lxml** + **BeautifulSoup4** | lxml 速度快，BS4 容错好、上手快 |
| **正文抽取** | **trafilatura** | ⭐ 开源里质量最好的正文抽取（去导航/页脚/广告），中文站点表现也好 |
| **结构化数据抽取** | **extruct** | ⭐ 直接吐出页面所有 JSON-LD / Microdata / RDFa，是 Schema.org 检查项的刚需 |
| **JS 渲染** | **Playwright (Python)** | CSS/XPath 选择器与解析层同构；渲染前后 HTML 对比可识别渲染不一致与 cloaking 风险 |
| **任务队列** | **Celery**（+ Redis）或 **Dramatiq** | 扫描任务长耗时、可重入。Celery 功能全但重，Dramatiq 更轻；编排复杂度上来再上 Temporal |
| **LLM 编排** | **instructor** + **litellm** | ⭐ instructor 把 LLM 输出直接校验为 Pydantic 实例（不过就重试），从根上防幻觉传导；litellm 统一 DeepSeek/OpenRouter/Claude |
| **中文 NLP** | **jieba** / **hanlp** | 中文分词与实体识别，Go/Java 均无成熟替代 |
| **嵌入/相似** | sentence-transformers（可选）+ pgvector | 首版用远程 API 即可，不本地训模型 |
| **结构化日志** | **structlog** | JSON 日志，与 OpenTelemetry 无缝集成 |
| **配置** | pydantic-settings | 12-factor，环境变量即配置 |
| **前端** | Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui | 生态最大，shadcn 提供可复制组件，设计感可控 |
| **UI 增强** | Recharts（图表）、TanStack Table（复杂表格）、React Flow（站点地图/内链图可视化） | 三个难替代的场景 |
| **对象存储** | S3 兼容（MinIO 自托管 / 阿里云 OSS） | 页面快照、报告 PDF |
| **数据源（第三方）** | DataForSEO / SerpAPI / GSC API / 百度搜索资源平台 API / GA4 Data API | 全部做成 Provider 接口，方便替换；中英文市场各配一套 |
| **AI** | **litellm**（多 provider 统一）+ **instructor**（结构化输出强校验）；DeepSeek 主力（中文/成本），Claude/GPT 处理高难内容 | Python 生态 LLM 支持最完整；instructor 避免手写 JSON 解析与重试 |
| **鉴权** | python-jose / PyJWT + 前端 Auth.js | |
| **计费** | Stripe（海外）/ 自建额度系统（国内） | |
| **可观测** | OpenTelemetry (Python SDK) + Grafana + Loki + Sentry | 抓取任务必须有 trace，排查成本黑洞 |
| **CI/CD** | GitHub Actions + ruff + mypy + pytest；生产 Docker Compose → K8s | |
| **Monorepo** | uv workspace / pnpm workspace | 前后端共享 Pydantic 生成的 JSON Schema 契约 |
| **部署** | Docker（slim base + uv 依赖裁剪）→ Compose 单机起步；后续 Fly.io / K8s | |

### 4.2.1 Python 侧的已知短板与对策

| 短板 | 影响 | 对策 |
|---|---|---|
| 动态类型，错误运行时才暴露 | 后期维护成本上升 | 全程 Pydantic 做类型契约 + mypy strict + ruff；关键路径写类型标注 |
| 抓取内存占用高于 Go | 大规模并发时内存吃紧 | 抓取器独立进程可水平扩展；先实测本项目量级（1w~10w URL）再决定是否优化 |
| GIL | CPU 密集任务（正文处理、规则计算）难并行 | Celery 进程池/线程池隔离；或直接多 worker 进程 |

**结论**：三张短板均在可控范围，且有标准解法；相比 Go 方案在 65% 的复杂度上换来的开发速度收益，净利很大。

### 4.3 目录结构建议

```
seo-agent/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── worker.py          # Celery 消费者（Agent 执行体）
│   │   ├── core/              # config / logging / security / errors
│   │   ├── models/            # ★ Pydantic（领域模型 + LLM 输出契约 + API schema）
│   │   ├── db/                # SQLAlchemy models / session / repository
│   │   ├── api/               # routers（sites/issues/keywords/content/rankings）
│   │   ├── crawler/           # scheduler / fetcher / rate_limiter / robots / frontier
│   │   ├── render/            # Playwright 渲染 + 渲染前后 diff
│   │   ├── extract/           # trafilatura 正文 + extruct Schema + lxml 元数据
│   │   ├── audit/             # ★ 规则引擎：注册 + 执行 + 评分
│   │   │   ├── engine.py
│   │   │   └── rules/         #   按生态分包
│   │   │       ├── base/      #   通用检查项
│   │   │       ├── google/    #   Google 生态
│   │   │       ├── baidu/     #   百度生态
│   │   │       └── cnh_eco/   #   微信/小红书/知乎扩展
│   │   ├── agents/            # crawl/audit/keyword/serp/content/prioritize/report
│   │   ├── llm/               # ★ litellm + instructor 封装（结构化输出强校验）
│   │   ├── providers/         # serp / gsc / ga4 / dfseo / baidu 统一抽象
│   │   ├── scoring/           # 健康分与优先级排序
│   │   └── report/            # 报告生成（Markdown / PDF / Excel / PR diff）
│   ├── migrations/            # Alembic
│   ├── tests/
│   │   ├── golden/            # ★ 黄金样本集（100 个标注页面，防 Prompt 回归）
│   │   └── ...
│   └── pyproject.toml
├── frontend/
│   ├── app/                   # Next.js App Router
│   ├── components/ui/         # shadcn
│   └── ...
├── schemas/                   # ★ Pydantic 自动生成的 JSON Schema + 前端 TS 类型（单一真相源）
├── docs/
└── infra/                     # docker-compose、prometheus、grafana
```

**关键设计 1 —— 规则引擎分包**：`audit/rules/` 按搜索引擎生态分包。核心引擎只认 `Rule` ABC（`code / market / severity / check(page) -> list[Issue]`），**新增一个市场 = 新增一个包，不改核心代码**。这是支持中英文双生态的扩展性基础。

**关键设计 2 —— Pydantic 作为单一真相源**：Agent 之间的数据传递、以及 LLM 的结构化输出，全部用 Pydantic 模型约束。`instructor` 会把 LLM 返回直接校验成模型实例，**校验不过就重试**——这从根上杜绝了「上游 Agent 幻觉传导到下游」这个 Agent 系统最大风险。同时 `schemas/` 下的 JSON Schema 和前端 TS 类型由 Pydantic 自动生成，不存在手工同步不一致。

---

## 5. 界面与交互设计

### 5.1 设计方向
- **气质：克制、专业、数据密度高**。参考 Linear（交互质感）+ Vercel（排版秩序）+ Ahrefs（信息密度），不做花哨渐变。
- **暗色为默认**（开发者/增长人群使用时长长），亮色可切。
- 主色：单一品牌色（建议靛蓝/墨绿），其余用中性灰阶，状态色（成功/警告/危险）只在必要处出现。
- 排版：Inter / Geist，数字用 tabular-nums（表格对齐），字号层级严格 6 级以内。
- 动效：只用于状态反馈（扫描进度、结果流入），200ms 内，不做装饰性动画。

### 5.2 核心页面
1. **Onboarding**：输网址 → 授权 GSC → 选竞品 → 选语言/市场 → 开始扫描（进度可视化 + 预计时间）
2. **站点总览 Dashboard**：健康分环、模块雷达图、Top 问题卡、30 天趋势、竞品对比条
3. **问题详情页**：左侧问题列表，右侧证据（URL + 抓取快照 + 影响说明 + 修复代码块 + 一键应用）
4. **关键词与内容**：关键词表（意图/难度/量/排名）、内容日历（看板视图拖拽排期）、Brief 详情与生成
5. **页面优化工作台**：左原文右改写，diff 高亮，可预览 SERP 效果模拟
6. **排名监控**：趋势线、页面维度、告警列表
7. **站点地图/内链图**：力导向图，节点=页面，边=内链，按流量/深度着色

### 5.3 交互原则
- **渐进披露**：先给"3 件最该做的事"，细节折叠；不要一上来甩 200 个问题
- **每条建议可执行**：必须含复制即用的代码/配置/文案，不能只有描述
- **危险操作二次确认 + 自动备份**
- 键盘快捷键（`/` 搜索、`j/k` 遍历问题、`a` 应用）——目标用户是熟练工
- 空状态有引导，不写"暂无数据"了事

---

## 6. 数据模型（核心表）

```sql
sites(id, domain, settings, created_at)
crawl_jobs(id, site_id, status, started_at, finished_at, url_count)
pages(id, site_id, url, status_code, title, meta_desc, canonical,
      depth, word_count, rendered_hash, fetched_at, snapshot_uri)
issues(id, site_id, code, severity, url, evidence_json, impact, fix_hint, status)
keywords(id, site_id, term, volume, difficulty, intent, cluster_id, tracked_at)
serp_snapshots(id, keyword_id, position, url, title, features, captured_at)
content_briefs(id, site_id, target_url, keyword_id, brief_json, status)
suggestions(id, site_id, url, type, before_text, after_text, applied_at, reverted_at)
rank_history(site_id, url, keyword_id, date, position, clicks, impressions, ctr)
```

---

## 7. API 轮廓

```
POST   /v1/sites                          创建站点
POST   /v1/sites/{id}/crawl               触发扫描
GET    /v1/sites/{id}/crawl/{jobId}      进度/状态
GET    /v1/sites/{id}/issues             问题列表（分页/筛选）
PATCH  /v1/issues/{id}                   标记状态
POST   /v1/suggestions/{id}/apply        应用（写回或生成 PR）
GET    /v1/sites/{id}/report             生成报告
GET    /v1/keywords                      关键词
POST   /v1/content/brief                 生成 Brief
GET    /v1/rankings/history
POST   /v1/webhooks                      事件订阅（scan.completed / rank.dropped）
```
- 认证：API Key（`sk_live_...`）+ 签名 Webhook
- 限流：按套餐，返回 `X-RateLimit-*`
- 对外同时提供 **MCP Server**（stdio + HTTP），让 AI 助手直接调用

---

## 8. 非功能性需求

| 维度 | 目标 |
|---|---|
| 可用性 | 99.9%（Web）；任务失败自动重试 3 次 + 死信 |
| 性能 | 页面首屏 <1.5s；Dashboard API P95 <300ms；报告异步生成 |
| 规模 | 单站 10w URL 扫描 <30min；100 并发租户 |
| 安全 | 抓取遵守 robots（可配置）、SSRF 防护、密钥进 Vault/环境变量不出现在代码、API 全 TLS |
| 合规 | GDPR（数据删除/导出）、爬虫合规审查、不做"保证排名"类承诺 |
| 可观测 | 每站点扫描可 trace；LLM 成本按站点归集 |

---

## 9. 里程碑与排期

| 阶段 | 周期 | 交付 |
|---|---|---|
| **M0 原型验证** | 2 周 | 单站点爬取 + 20 条技术检查 + 简易报告（CLI/极简页面），验证价值 |
| **M1 MVP** | +4 周 | P0 全部功能：多站点、GSC、60+ 检查、关键词、Brief、改写、报告、前端完整 UI |
| **M2 增长** | +4 周 | P1：排名监控、竞品、内链、Schema、GEO |
| **M3 商业化** | +6 周 | 多租户、计费、插件、MCP、通知 |

**M0 的最小验证清单**（必须先跑通，别先做界面）：
1. 抓 1000 个 URL 不崩、能断点续跑
2. 60+ 检查项至少 50 条能稳定复现（用人工核对 20 个站点）
3. 产出 30 条建议，其中 ≥20 条站长认可"确实该改"

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 数据源成本高（SERP/关键词 API） | 毛利被吃光 | 分层缓存 + 只对变化页重查 + 预算熔断；提供自建抓取兜底 |
| LLM 建议质量波动 | 用户不信任 | 规则层做硬检查、LLM 只做策略；黄金样本回归测试；建议必须带证据 |
| Google 政策/算法变动 | 功能失效 | 规则配置化（YAML），不硬编码；社区维护 |
| 竞品（大厂）碾压 | 差异化弱 | 死磕"GEO/AI 搜索优化 + 自动执行闭环"，大厂做不动执行层 |
| 抓取引发的法律/封禁风险 | 服务器被封 | 限速、UA 声明、可配 robots、IP 池隔离 |
| 越权改站 | 数据事故 | 默认只读，写入走 PR/diff + 确认 + 备份 |

---

## 11. 差异化护城河（必须有，别人抄不走的）

1. **执行闭环**：从诊断到改写稿到 PR，全链路自动化——这是大多数工具的终点只是我们的起点
2. **GEO / AI 搜索可引用性优化**：抢先布局 AI 搜索（ChatGPT/Perplexity/AI Overviews）的评估与优化方法论
3. **证据链**：每条建议可点开看到原始抓取快照——信任的来源
4. **MCP 化**：让 AI 编码助手在用户代码库里直接调用 SEO 检查，形成飞轮
5. **垂直行业模板**：Shopify/独立站 SaaS/SaaS 软件站 的行业化检查规则包

---

## 12. 已确认的决策

| # | 问题 | 决策 |
|---|---|---|
| 1 | 目标市场 | ✅ **中英文双生态**：规则引擎分包（google / baidu / cnh_eco），数据按 market 隔离 |
| 2 | 后端语言 | ✅ **Python 3.12**（Go 方案已评估并否决，理由见 4.1 选型评估记录） |
| 3 | 前端 | ✅ Next.js 15 + React 19 + TS + Tailwind v4 + shadcn/ui |
| 4 | 目标客户优先级 | ⏳ 待定：建议先打 **P1 独立站/中小电商站长**（付费意愿强、需求标准化、易做自动化） |
| 5 | 交付形态 | ⏳ 待定：建议 **先本地/自托管跑通 M0，再包 SaaS 多租户**（避免过早引入鉴权/计费复杂度） |
| 6 | 预算 | ⏳ 待定：M0 阶段可以**零 API 成本**（纯自建抓取跑通技术体检），关键词/SERP API 等有付费用户后再接 |

---

## 13. 下一步

**第 1 步：M0 技术方案**（已就绪，待开工）
- 数据库 schema（Pydantic 模型 + Alembic 迁移）
- 爬虫详细设计：URL frontier 队列、并发控制、限速、断点续传、robots 解析
- 规则引擎设计：`Rule` ABC + 注册机制 + 分市场加载
- 前 20 个检查项的具体规则定义
- LLM 层设计：`instructor` 结构化输出契约 + 重试/降级策略

**第 2 步：项目骨架**
- uv 项目结构 + FastAPI 入口 + Celery worker + docker-compose（PG + Redis）+ CI（ruff/mypy/pytest）

**第 3 步：M0 验证**
- 抓 1000 URL 不崩、能断点续跑
- 20 条检查项能稳定复现，人工核对 20 个站点
- 产出 30 条建议，≥20 条被认可

**第 4 步：低保真原型**
- 页面线框 + 交互流，确认设计感方向
