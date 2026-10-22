<div align="center">

# 🦞 SEO-Claw

**基于正面证据的站点 SEO 审计工具 —— 宁可漏报，不报假问题**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-726%20✓-2EA44F?logo=pytest&logoColor=white)](#-开发与测试)
[![Coverage](https://img.shields.io/badge/coverage-80.2%25-2EA44F)](#-开发与测试)
[![License](https://img.shields.io/badge/license-MIT-FF9900)](#-license)
[![Code style](https://img.shields.io/badge/style-audit%20grade-black)](./DESIGN.md)

抓取站点 → 执行规则审计 → 产出可直接照着改的报告<br>
每一条问题都要求正面证据支撑；证据不足时保持沉默，并明确列出未覆盖的页面

[English](README.en.md) 　|　 **快速上手** · [安装](#-安装) · [一键体检](#-快速开始)

</div>

---

## 📑 目录

- [🎯 项目简介](#-项目简介)
- [✨ 核心特性](#-核心特性)
- [🔬 准确性与验证](#-准确性与验证)
- [📦 安装](#-安装)
- [🚀 快速开始](#-快速开始)
- [🎛️ 命令与参数](#️-命令与参数)
- [📏 规则覆盖](#-规则覆盖)
- [🧾 输出格式](#-输出格式)
- [🌐 Web 服务与 API](#-web-服务与-api)
- [🤝 爬虫礼仪与性能边界](#-爬虫礼仪与性能边界)
- [🚢 部署](#-部署)
- [🏗️ 架构](#️-架构)
- [🧪 开发与测试](#-开发与测试)
- [📐 设计原则](#-设计原则)
- [🗺️ 路线图](#️-路线图)
- [📜 License](#-license)

---

<a id="-项目简介"></a>
## 🎯 项目简介

绝大多数 SEO 工具输出一张两百条的红字清单：不分优先级、不给证据、误报混杂其中。用户照着一条误报去修改（例如「危险：屏蔽了百度收录」），结果那是站点自身的策略，改完流量反而归零。

**SEO-Claw 的设计目标正相反：每一条结论都必须有可回溯的正面证据，拿不到证据就不报。**

| | 🏭 典型 SEO 工具 | 🦞 SEO-Claw |
|---|---|---|
| 🎯 规则触发门槛 | 「未检出」即判定缺失 | 必须有**正面证据**，否则沉默 |
| 📊 站点级规则 | 无论覆盖率一律上报 | 覆盖率不足时**自动沉默** |
| 🕳️ 抓取失败 | 不披露，报告看似完整 | 明确列出**未审到的页面** |
| 📈 搜索量数据 | 填 0（暗示确无搜索量） | 拿不到数据时**留空** |
| 🧪 准确率表述 | 厂商自述，方法不公开 | **逐条回源核对**，方法与工具随仓库公开 |

<a id="-核心特性"></a>
## ✨ 核心特性

| | 能力 |
|---|---|
| 🧭 | **规则引擎** —— 43 条检查项按市场分包（base / google / baidu / cnh_eco / geo），页面级与站点级分层，实验包与已验证规则物理隔离 |
| 🕷️ | **礼貌爬虫** —— BFS 抓取、限速、自适应降速、熔断、代理轮换、断点续传、ETag/304 增量扫描 |
| 🧾 | **多格式报告** —— 终端 / Markdown / JSON / 单文件 HTML（无外链、可离线打开、可直接交付客户） |
| 🩹 | **整改工单（处方包）** —— 把问题变成「改前 → 改后」的可落地修复动作，md / json / csv / diff 四格式；可信度分三档（可照抄 / 机器起草待润色 / 只给配方），判不了的转人工不硬凑 |
| 📉 | **排名监测数据入口** —— 日级排名/流量 CSV 导入（`rank-import`）+ REST 接入，喂活排名时序与跌落告警；坏行逐行报错，区间聚合数据拒收 |
| 🔍 | **SERP 快照数据入口** —— 竞品位次导入（CSV / JSON，`serp-import`）+ REST 接入，喂活内容 Brief 的竞品维度；位次必须是整数名次，「平均排名」请走 `rank-import` |
| 🔑 | **关键词模块** —— 语料挖掘 + 词形聚类，**纯离线、确定性、无需任何 API key** |
| 📝 | **内容 Brief** —— 竞品共性取自 SERP 快照、我方位次取自排名历史、结构建议取自本站页面；哪块没数据就明说哪块缺失 |
| 🤖 | **可选 LLM 总结** —— `--llm-summary`，兼容任意 OpenAI 协议端点（OpenRouter / DeepSeek / Ollama / 自建网关） |
| 🖥️ | **Web 工作台** —— 仪表盘、一键体检、问题流转、报告导出、排名监测、多租户 API Key 与额度 |
| ⏱️ | **持久任务队列与定时复扫** —— 扫描任务落库、进程重启不丢活儿；托管站点按周期自动复扫（认领先于入队，宁可少扫一次也不给目标站双倍压力） |
| 🗄️ | **持久化** —— 13 张表 + Alembic 迁移，默认 SQLite，生产可切 PostgreSQL |
| 🔌 | **MCP Server** —— 3 个只读工具，供 AI 助手直接调用审计能力 |
| 🎭 | **JS 渲染** —— `--render-js` 可选启用（需 Chromium，不随默认镜像分发） |

<a id="-准确性与验证"></a>
## 🔬 准确性与验证

工具的每条规则都经过**回源核对**：在 100+ 个真实站点（博客、电商、文档站、政府站、中文社区、大型企业站）上实跑，然后逐条回到原页面验证「页面里到底有没有这个问题」——不是判断描述是否合理，而是核对事实是否成立。

验证过程中修正的两类问题均有记录：

1. **🐛 规则误报**（如 JS 注入 `<title>` 被误判缺失、翻译视图下的中文标题过长）——修正判据本身，而非简单调阈值；
2. **🧰 工具自身缺陷**（如 sitemap 索引误判导致 12/58 条假阳性）——修复后以真实站点复验并补回归测试。

完整的核对记录、复核器与语料随仓库公开：

- 📒 `docs/verification-ledger.md` —— 验证台账
- 🔧 `tools/verify_*.py` —— 回源核对器，可自行复跑
- 🗂️ `reports/` —— 核对轮次的 JSON 证据

> **⚠️ 诚实边界**：抽样回源只能覆盖报得最多的规则；未逐条核验的部分不宣称具体准确率数字。实验性 `geo` 包（AI 搜索引用性）证据强度弱于 base，默认不加载。

<a id="-安装"></a>
## 📦 安装

要求 **Python 3.11+**（开发与 CI 环境为 3.12）。

### 源码安装（当前唯一受支持的方式）

```bash
git clone https://github.com/Geek0ne/SEO-Claw.git
cd SEO-Claw
pip install -e ".[api,dev]"        # 📌 CLI + Web/API + 测试
```

<details>
<summary>🔧 其他安装组合</summary>

```bash
# 仅命令行扫描（不装 FastAPI 层）
pip install -e .

# PostgreSQL 持久化 + MCP Server
pip install -e ".[api,postgres,mcp]"
```

</details>

安装后提供两个等价的命令行入口：`seo-claw`（与项目名一致）与兼容别名 `seoclaw`。

> 💡 PyPI 尚未发布本包，`pip install seoclaw` / `pip install seo-claw` 目前不可用。

<a id="-快速开始"></a>
## 🚀 快速开始

```bash
seoclaw scan example.com                  # 📟 报告输出到终端
seoclaw scan example.com -o report.md     # 📄 Markdown
seoclaw scan example.com --html out.html  # 🌐 单文件 HTML，可直接发客户
seoclaw scan example.com --json           # 🔗 JSON 输出
seoclaw rules                             # 📏 看看会查些什么
```

<a id="️-命令与参数"></a>
## 🎛️ 命令与参数

### `seoclaw scan <url>`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--max-pages` | 100 | 🔢 抓取页面上限 |
| `--max-depth` | 6 | 📉 BFS 最大深度 |
| `--rps` | 3.0 | ⏱️ 单域每秒请求数 |
| `--market` | `base` | 🌍 规则市场包，可重复叠加：`base` / `google` / `baidu` / `cnh_eco` / `geo` |
| `--output, -o` | – | 📄 Markdown 报告输出路径 |
| `--html` | – | 🌐 单文件 HTML 报告输出路径 |
| `--fixpack` | – | 🩹 整改工单输出路径（格式按扩展名：`.md` / `.json` / `.csv` / `.diff`） |
| `--brand` | – | 🏷️ 白标交付：报告与工单落款换成这个名字（代理商交付客户用） |
| `--json` | – | 🔗 JSON 输出 |
| `--db` | 不落库 | 🗄️ 持久化路径或连接串（不指定则不建库） |
| `--checkpoint` | – | 💾 断点续传目录 |
| `--incremental` | – | ♻️ 增量扫描（ETag/304），需配合 `--checkpoint` |
| `--render-js` | 关 | 🎭 JS 渲染（需 Chromium） |
| `--proxy` / `--proxy-file` | – | 🌉 代理（可重复 / 从文件逐行读取） |
| `--llm-summary` | 关 | 🤖 追加 AI 总结（需 OpenAI 兼容端点） |
| `--ignore-robots` | 关 | ⚠️ 仅限调试自有站点 |
| `--quiet, -q` | – | 🔇 静默模式 |

### `seoclaw rules`

列出全部已加载检查项（规则编号、严重级、标题），分「页面级 / 站点级」两栏。

### `seoclaw rank-import <csv> --db seo.db`

导入**日级**排名/流量数据（GSC API / BigQuery / 排名跟踪器导出），驱动排名
监测与跌落告警。列名认别名（`page`/`average position`/`query`…）；⚠️ GSC
**网页版**导出是区间聚合（无日期列），会直接拒收——假时序比没时序更糟。

### `seoclaw serp-import <csv|json> --db seo.db --site example.com`

导入一次 SERP 抓取快照（Top10 竞品位次），喂给内容 Brief 的竞品维度。
CSV / JSON 都认（不给 `--format` 时按扩展名和内容自动判断），列名同样认
别名（`keyword`/`query`/`搜索词`、`url`/`link`、`position`/`rank`/`排名`…）。

两条硬规矩，都是「宁可拒收也不污染结论」：

- ⚠️ `--site` **必填**。一次抓取里多数结果是竞品页面，按「出现最多的域名」
  自动匹配会把数据灌到竞品名下，所以不猜。
- ⚠️ `position` 必须是**整数名次**（1、2、3…）。小数平均排名属于排名时序，
  请走 `rank-import`；把两者混进一张表，Top N 会算出一堆假共性。

文件没写抓取时间时按「今天 00:00 UTC」记为一次快照（终端会明确打出来），
重复导入同一 (关键词, 时刻, URL) 是更新而不是插第二份。REST 侧对应
`POST /api/v1/sites/{id}/serp` 与 `GET /api/v1/sites/{id}/serp`。

<a id="-规则覆盖"></a>
## 📏 规则覆盖

**规则库共 43 条**，按市场分包、按需组合：

| 包 | 市场 | 条数（页面级 / 站点级） | 启用方式 |
|---|---|---|---|
| 🟢 `base` | 通用 | **22**（15 / 7） | 默认加载 |
| 🔵 `google` | Google | **11**（10 / 1） | `--market google` |
| 🟠 `baidu` | 百度 | **5**（3 / 2） | `--market baidu` |
| 💬 `cnh_eco` | 微信搜一搜 | **1**（0 / 1） | `--market cnh_eco` |
| 🧪 `geo` | AI 搜索引用性（实验性） | **4**（4 / 0） | `--market geo`（点名才加载，不进默认扫描） |

`--market` 采用叠加语义（始终包含 `base`）：

```bash
seoclaw scan example.com                     # 22 条（base）
seoclaw scan example.com --market google     # 33 条（base + google）
seoclaw scan example.com --market baidu      # 27 条（base + baidu）
seoclaw scan example.com --market baidu --market google   # 38 条
```

**覆盖范围**：title / meta description / H1 / canonical / noindex / 图片 alt / 内链锚文本 / 点击深度 / 孤岛页 / 混合内容 / 结构化数据 / 软 404 / sitemap / robots.txt / hreflang / viewport / Open Graph / ICP 备案 / 微信搜一搜可索引性等。

### 🤫 有意为之的「沉默」

以下情形工具**刻意不报**——报了就是错的：

- 🚫 站点主动屏蔽搜索引擎收录 → 标记 `possibly_intentional`，降为 INFO 级
- 📉 覆盖率不足时的站点级结论（「未检出内链」推不出「站点没有内链」）
- 🎭 JS 渲染页面的静态检查项
- 🤔 可能是有意为之的关键词堆砌 / 低质量标题

<a id="-输出格式"></a>
## 🧾 输出格式

| 格式 | 参数 | 用途 |
|---|---|---|
| 📟 终端 | （默认） | 快速查看 |
| 📄 Markdown | `-o report.md` | 归档、评审 |
| 🔗 JSON | `--json` | 程序化处理 |
| 🌐 单文件 HTML | `--html out.html` | 无外链、可离线打开、可直接交付客户 |

报告结构：**健康分**（0–100，分维度）→ **「最该先做的 5 件事」** → 分级折叠的问题清单（每条含证据、影响、修复建议与示例代码）→ **未覆盖页面披露**。

<a id="-web-服务与-api"></a>
## 🌐 Web 服务与 API

```bash
uvicorn seoclaw.main:app --port 8000
```

浏览器打开即可使用——**Web 全功能工作台**（详见 [docs/web-feature-matrix.md](docs/web-feature-matrix.md)）：

- 📊 **仪表盘**：全站健康分与最近扫描总览
- ⚡ **一键体检**：后台扫描 + 进度轮询，不阻塞浏览器
- 🧩 **问题流转**：筛选、单条/按根因批量标记（待处理 / 已知晓 / 已修复 / 误报）
- 🧾 **报告与导出**：md / html / json 一键带走
- 📈 **趋势与历史**：健康分曲线 + 扫描任务列表
- 🩹 **整改工单**：`GET /sites/{id}/fixpack`（md / json / csv / diff）+ 排名数据接入 `POST /sites/{id}/rankings`
- 🔑 **多租户**：API Key（只存哈希）、额度、站点归属验证
- 🔌 **REST API**：28 个路径、36 个操作（按 OpenAPI 实数）+ **MCP Server**（3 个只读工具）

<a id="-爬虫礼仪与性能边界"></a>
## 🤝 爬虫礼仪与性能边界

对第三方站点保持礼貌是硬约束，由此产生一条**必须明确的性能边界**：

- 🐢 默认 **3 req/s**，遵守 `robots.txt` 与对方声明的 `Crawl-delay`
- 📉 遇 429/403 自适应降速；连续 5 次连接失败熔断中止本域（避免延长封禁）
- ⏳ **1000 页的站点实测约需 6.4 分钟**：`3 req/s × 1000 页 ≈ 333 秒` 是墙钟下界（5.5 分钟），实测 382 秒中 87% 花在等待限速。**增加并发无法缩短**——限速器按墙钟串行放行。这是设计取舍，不是性能缺陷
- 🚫 **不为了让数字好看而提高默认速率**。2026-10-22 明确决策：默认 3 req/s 保持不动，「1000 页 ≤5 分钟」这条早期拍的验收指标**作废**，改为按实测引用（见 `PLAN.md` M0 清单）
- ✅ 实测 `docs.python.org` 抓取 1000 页：382 秒，991 成功 / 9 失败，中断后可续跑

<a id="-部署"></a>
## 🚢 部署

```bash
docker compose up -d        # 🔒 默认仅绑定 127.0.0.1:8000
```

| 方式 | 说明 |
|---|---|
| 🐳 `Dockerfile` | 非 root 运行、依赖层缓存、健康检查探活 `/api/v1/health` |
| 🧱 `docker-compose.yml` | 数据卷、日志轮转（防磁盘写满）、SQLite / PostgreSQL 可切换 |
| ☁️ `render.yaml` | Render 免费版一键部署（含免费版限制说明与默认降配） |
| 🚨 上线前验收 | `./tools/guard_smoke.sh` —— 11 个用例实测 SSRF、限流、并发、黑名单四道闸 |

> ⚠️ **单测全绿不代表容器里的闸活着**，`guard_smoke.sh` 是上线前的最后一道。

完整选型与成本测算见 **[DEPLOY.md](DEPLOY.md)**（实测数据：CPU 非瓶颈、峰值内存约 100 MB、镜像 438 MB）。

<a id="️-架构"></a>
## 🏗️ 架构

```
backend/seoclaw/
├── 🕷️ crawler.py       BFS 抓取：限速 / 自适应降速 / 熔断 / 代理轮换 / 断点续传
├── 📄 extract.py       HTML → Page（trafilatura 正文抽取）
├── 🧭 audit/
│   ├── ⚙️ engine.py    规则执行 + 站点级事实（覆盖率、hit_page_limit）
│   └── 📏 rules/       base / google / baidu / cnh_eco / geo
├── 🔑 keywords/        关键词扩展 + 聚类（纯离线，无需 API key）
├── 📝 brief.py         内容 Brief 生成（竞品维度取 SERP，我方位次取排名历史）
├── 📉 rankdata.py      日级排名数据入口（CSV 别名 + 逐行报错 + 幂等 upsert）
├── 🔍 serpdata.py      SERP 快照数据入口（CSV / JSON，位次必须是整数名次）
├── 🩹 fixpack.py       整改工单：问题 → 「改前 → 改后」，三档可信度
├── 🤖 llm.py           可选 LLM 总结（OpenAI 兼容协议，0 新增依赖）
├── ⏱️ tasks.py          持久任务队列：认领 → 执行 → 收尾，重启不丢活儿
├── ⏰ scheduler.py     定时复扫：到期站点变成队列里的一条任务
├── 🧾 log.py           结构化日志收口（替代 print 到 stderr）
├── 🗄️ db/              13 表 + Alembic 迁移
├── 🧾 report.py        Markdown 报告
├── 🌐 report_html.py   单文件 HTML 报告
├── 🖥️ web/             在线工作台（quick-scan + 进度轮询）
├── 🔌 api/             FastAPI 服务层（鉴权 / 额度 / 归属验证 / 导出）
└── 🧰 mcp_server.py    MCP Server（3 个只读工具）
```

**约 17,800 行实现代码 · 约 11,200 行测试代码 · 726 个测试（实跑全绿；行数按 `backend/seoclaw` 与 `backend/tests` 下的 `.py` 统计）。**

### 🗄️ 数据库

13 张表：`sites` / `crawl_jobs` / `pages` / `issues` / `keywords` /
`serp_snapshots` / `content_briefs` / `suggestions` / `api_keys` /
`rank_alert_acks` / `usage_events` / `rank_history` / `scan_tasks`。

```bash
cd backend && alembic -c migrations/alembic.ini upgrade head
```

> ⚠️ 上线**必须走 Alembic 迁移**。`create_all` 只保证空库能启动，**不会为已有库补新列**——混用会制造「测试正常、生产 500」的静默故障。

<a id="-开发与测试"></a>
## 🧪 开发与测试

```bash
git clone https://github.com/Geek0ne/SEO-Claw.git
cd SEO-Claw
pip install -e ".[api,dev]"
pytest backend/tests -q
```

- ✅ **726 个测试**：本机全绿；未安装可选依赖 `mcp` 时其中 3 条（`test_mcp_server.py`）跳过
- 📊 覆盖率 80.2%（本机 `pytest --cov` 实测，CI 门禁 78%，余量 2.2 个点）。同一份
  代码连跑会在 80.14%–80.18% 之间微漂，漂的是 `db/session.py` 里的 `create_all`
  那一行：测试用例共用一个引擎单例与同一个 sqlite 文件，个别跑法下它会以
  `database is locked` 失败并被吞进日志（用例仍全绿，但那条语句没被执行到）。
  **别再追着这 0.04 个点改文档**，根因与修法记在 PLAN 技术债。缺口
  正在收：`cli.py` 从 28% 提到 41%（`rank-import` / `rules` / argparse 派发已补
  命令级用例），`api/routes.py` 仍是 37% 的薄接线——规则层、DB 层、解析层都有
  用例，**接线层靠人肉冒烟的时代该结束了**。补法照 `test_cli_persist.py` 里的
  命令级范本（真文件 + 真临时库），**而不是下调阈值**
- 🔢 README 自己的宣传数字有回归网（`test_docs_stats.py`）：表数与表名对着
  `Base.metadata.tables` 核、路径/操作数对着 `app.openapi()` 核、中英两份的测试数
  与覆盖率徽标必须彼此一致。**数字写两处就一定会分叉**，这条不是洁癖
- 🤖 **CI 双任务**：① 全量测试 + 覆盖率 + CLI 冒烟 + wheel 构建；② `guard_smoke.sh` 真容器验收（四道闸）
- 🧰 部分环境用 `run.sh` 封装本机依赖安装方式（`.deps/` 隔离 + `PYTHONPATH`），见脚本内注释

### 📚 相关文档

| 文档 | 内容 |
|---|---|
| 🚢 [DEPLOY.md](DEPLOY.md) | 部署选型、成本实测与更新指南 |
| 🎨 [DESIGN.md](DESIGN.md) | Web 界面设计系统（唯一事实来源） |
| 📋 [REQUIREMENTS.md](REQUIREMENTS.md) · [PLAN.md](PLAN.md) | 产品需求与演进规划 |
| 🌐 [docs/web-feature-matrix.md](docs/web-feature-matrix.md) | Web 功能矩阵与补齐记录 |
| 🤝 [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南与新增规则的门槛 |
| 🔒 [SECURITY.md](SECURITY.md) | 安全政策与攻击面说明 |
| 📝 [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

<a id="-设计原则"></a>
## 📐 设计原则

以下约束由实测教训固化而来，是代码层面的硬规矩：

1. 🎯 **只报有正面证据的问题**——「未检出」推不出「不存在」
2. 🤫 **覆盖率不足时，站点级规则必须沉默**
3. 📋 **报告必须列出未审到的页面**——避免读者把「没审成」理解为「没问题」
4. 🚫 **无付费数据源时，搜索量字段留 `null`**，不填 0
5. 🔒 **`--db` 未指定时不落库**——不主动为用户创建数据库文件
6. 🛟 **落库失败不得让报告消失**——增强层故障不拖垮主结果
7. 🧪 **实验性规则与已验证规则物理隔离**——`geo` 包需显式启用

<a id="️-路线图"></a>
## 🗺️ 路线图

当前版本聚焦「技术 SEO 审计」的准确性与可交付性。规划中的方向（详见 [REQUIREMENTS.md](REQUIREMENTS.md) / [PLAN.md](PLAN.md)）：

- 📈 SERP 排名与流量监测、异动告警（两类数据入口都已通：日级排名 `rank-import` / `POST /rankings`，SERP 快照 `serp-import` / `POST /serp`；接真实数据源即用）
- ✍️ 页面改写与执行闭环第二步：处方已能开「改前 → 改后」，下一步是平台适配器（WordPress/Shopify 插件）与 PR diff 自动提交
- 🆚 竞品追踪与内容缺口分析（竞品位次已能落库并喂给 Brief；跨词缺口对比、竞品集合管理还没做）
- 📅 内容日历与批量 Brief
- 📤 一键导出 PR diff / PDF / Excel

<a id="-license"></a>
## 📜 License

[MIT](LICENSE) © 2026 Geek0ne
