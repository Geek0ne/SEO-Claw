<div align="center">

# SEO-Claw

**基于正面证据的站点 SEO 审计工具 —— 宁可漏报，不报假问题**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-618%20passed-brightgreen)](#开发与测试)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

抓取站点 → 执行规则审计 → 产出可直接照着改的报告。
每一条问题都要求正面证据支撑；证据不足时保持沉默，并明确列出未覆盖的页面。

**English**: [README.en.md](README.en.md)

</div>

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [准确性与验证方法](#准确性与验证方法)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令与参数](#命令与参数)
- [规则覆盖](#规则覆盖)
- [输出格式](#输出格式)
- [Web 服务与 API](#web-服务与-api)
- [爬虫礼仪与性能边界](#爬虫礼仪与性能边界)
- [部署](#部署)
- [架构](#架构)
- [开发与测试](#开发与测试)
- [设计原则](#设计原则)
- [路线图](#路线图)
- [License](#license)

---

## 项目简介

绝大多数 SEO 工具输出一张两百条的红字清单：不分优先级、不给证据、误报混杂其中。用户照着一条误报去修改（例如「危险：屏蔽了百度收录」），结果那是站点自身的策略，改完流量反而归零。

SEO-Claw 的设计目标正相反：**每一条结论都必须有可回溯的正面证据，拿不到证据就不报。**

| | 典型 SEO 工具 | SEO-Claw |
|---|---|---|
| 规则触发门槛 | 「未检出」即判定缺失 | 必须有**正面证据**，否则沉默 |
| 站点级规则 | 无论覆盖率一律上报 | 覆盖率不足时**自动沉默** |
| 抓取失败 | 不披露，报告看似完整 | 明确列出**未审到的页面** |
| 搜索量数据 | 填 0（暗示确无搜索量） | 拿不到数据时**留空** |
| 准确率表述 | 厂商自述，方法不公开 | **逐条回源核对**，方法与工具随仓库公开 |

## 核心特性

- **规则引擎**：43 条检查项按市场分包（base / google / baidu / cnh_eco / geo），页面级与站点级分层，实验性规则包与已验证规则物理隔离
- **爬虫**：BFS 抓取、限速、自适应降速、熔断、代理轮换、断点续传、ETag/304 增量扫描
- **多格式报告**：终端 / Markdown / JSON / 单文件 HTML（无外链、可离线打开、可直接交付客户）
- **关键词模块**：语料挖掘 + 词形聚类，**纯离线、确定性、无需任何 API key**
- **内容 Brief**：基于 SERP 快照与本站页面生成写作 Brief，数据边界如实标注
- **可选 LLM 总结**：`--llm-summary`，兼容任意 OpenAI 协议端点（OpenRouter / DeepSeek / Ollama / 自建网关）
- **Web 服务**：FastAPI 后台扫描 + 进度轮询，多租户 API Key、额度与站点归属验证
- **持久化**：12 张表 + Alembic 迁移，默认 SQLite，生产可切 PostgreSQL
- **MCP Server**：3 个只读工具，供 AI 助手直接调用审计能力
- **JS 渲染**：`--render-js` 可选启用（需 Chromium，不随默认镜像分发）

## 准确性与验证方法

工具的每条规则都经过**回源核对**：在 100+ 个真实站点（博客、电商、文档站、政府站、中文社区、大型企业站）上实跑，然后逐条回到原页面验证「页面里到底有没有这个问题」——不是判断描述是否合理，而是核对事实是否成立。

验证过程中修正的两类问题均有记录：

1. **规则误报**（如 JS 注入 `<title>` 被误判缺失、翻译视图下的中文标题过长）——修正判据本身，而非简单调阈值；
2. **工具自身缺陷**（如 sitemap 索引误判导致 12/58 条假阳性）——修复后以真实站点复验并补回归测试。

完整的核对记录、复核器与语料随仓库公开：

- `docs/verification-ledger.md` —— 验证台账
- `tools/verify_*.py` —— 回源核对器，可自行复跑
- `reports/` —— 各轮实测报告与 JSON 证据

> **诚实边界**：抽样回源只能覆盖报得最多的规则；未逐条核验的部分不宣称具体准确率数字。实验性 `geo` 包（AI 搜索引用性）证据强度弱于 base，默认不加载。

## 安装

要求 **Python 3.11+**（开发与 CI 环境为 3.12）。

### 源码安装（当前唯一受支持的方式）

```bash
git clone https://github.com/Geek0ne/SEOClaw.git
cd SEOClaw
pip install -e ".[api,dev]"        # CLI + Web/API + 测试
```

仅用命令行扫描（不装 FastAPI 层）：

```bash
pip install -e .
```

需要 PostgreSQL 持久化时追加 `postgres` extra；集成 MCP Server 追加 `mcp` extra：

```bash
pip install -e ".[api,postgres,mcp]"
```

安装后提供两个等价的命令行入口：`seo-claw`（与项目名一致）与兼容别名 `seoclaw`。

> 注：PyPI 尚未发布本包，`pip install seoclaw` / `pip install seo-claw` 目前不可用。

## 快速开始

```bash
seoclaw scan example.com                  # 报告输出到终端
seoclaw scan example.com -o report.md     # Markdown 报告
seoclaw scan example.com --html out.html  # 单文件 HTML，可直接发客户
seoclaw scan example.com --json           # JSON 输出
seoclaw rules                             # 查看已加载的检查项
```

## 命令与参数

### `seoclaw scan <url>`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--max-pages` | 100 | 抓取页面上限 |
| `--max-depth` | 6 | BFS 最大深度 |
| `--rps` | 3.0 | 单域每秒请求数 |
| `--market` | `base` | 规则市场包，可重复叠加：`base` / `google` / `baidu` / `cnh_eco` |
| `--output, -o` | – | Markdown 报告输出路径 |
| `--html` | – | 单文件 HTML 报告输出路径 |
| `--json` | – | JSON 输出 |
| `--db` | 不落库 | 持久化路径或连接串（不指定则不建库） |
| `--checkpoint` | – | 断点续传目录 |
| `--incremental` | – | 增量扫描（ETag/304），需配合 `--checkpoint` |
| `--render-js` | 关 | JS 渲染（需 Chromium） |
| `--render-timeout` | 20 | 单页渲染超时（秒） |
| `--proxy` / `--proxy-file` | – | 代理（可重复 / 从文件逐行读取） |
| `--llm-summary` | 关 | 追加 AI 总结（需 OpenAI 兼容端点） |
| `--ignore-robots` | 关 | ⚠️ 仅限调试自有站点 |
| `--no-verify-canonical` / `--no-verify-og-image` | – | 跳过对应的回源验证请求 |
| `--adaptive-backoff` | 开 | 遇 429/403 自适应降速（`--no-adaptive-backoff` 关闭） |
| `--quiet, -q` | – | 静默模式 |

### `seoclaw rules`

列出全部已加载检查项（规则编号、严重级、标题），分「页面级 / 站点级」两栏。

## 规则覆盖

**规则库共 43 条**，按市场分包、按需组合：

| 包 | 市场 | 条数（页面级 / 站点级） | 启用方式 |
|---|---|---|---|
| `base` | 通用 | **22**（15 / 7） | 默认加载 |
| `google` | Google | **11**（10 / 1） | `--market google` |
| `baidu` | 百度 | **5**（3 / 2） | `--market baidu` |
| `cnh_eco` | 微信搜一搜 | **1**（0 / 1） | `--market cnh_eco` |
| `geo` | AI 搜索引用性（实验性） | **4**（4 / 0） | `--market geo`（点名才加载，不进默认扫描） |

`--market` 采用叠加语义（始终包含 `base`）：

```bash
seoclaw scan example.com                     # 22 条（base）
seoclaw scan example.com --market google     # 33 条（base + google）
seoclaw scan example.com --market baidu      # 27 条（base + baidu）
seoclaw scan example.com --market baidu --market google   # 38 条
```

覆盖范围：title / meta description / H1 / canonical / noindex / 图片 alt /
内链锚文本 / 点击深度 / 孤岛页 / 混合内容 / 结构化数据 / 软 404 /
sitemap / robots.txt / hreflang / viewport / Open Graph / ICP 备案 /
微信搜一搜可索引性等。

### 有意为之的「沉默」

以下情形工具**刻意不报**——报了就是错的：

- 站点主动屏蔽搜索引擎收录 → 标记 `possibly_intentional`，降为 INFO 级
- 覆盖率不足时的站点级结论（「未检出内链」推不出「站点没有内链」）
- JS 渲染页面的静态检查项
- 可能是有意为之的关键词堆砌 / 低质量标题

## 输出格式

| 格式 | 参数 | 用途 |
|---|---|---|
| 终端 | （默认） | 快速查看 |
| Markdown | `-o report.md` | 归档、评审 |
| JSON | `--json` | 程序化处理 |
| 单文件 HTML | `--html out.html` | 无外链、可离线打开、可直接交付客户 |

报告结构：健康分（0–100，分维度）→ 「最该先做的 5 件事」→ 分级折叠的问题清单（每条含证据、影响、修复建议与示例代码）→ 未覆盖页面披露。

## Web 服务与 API

```bash
uvicorn seoclaw.main:app --port 8000
```

浏览器打开即可使用：输入网址 → 后台扫描 → 页面轮询进度，无需长连接等待。

- **REST API**：28 个端点，覆盖站点管理、扫描任务、问题清单、关键词、内容 Brief、健康分趋势、排名异动、用量额度、API Key 签发/撤销、站点归属验证
- **多租户**：API Key + 归属校验 + 免费额度
- **MCP Server**（`seoclaw.mcp_server`）：3 个**只读**工具，供 AI 助手调用；工具集即权限边界，不提供任何写操作

## 爬虫礼仪与性能边界

对第三方站点保持礼貌是硬约束，由此产生一条**必须明确的性能边界**：

- 默认 **3 req/s**，遵守 `robots.txt` 与对方声明的 `Crawl-delay`
- 遇 429/403 自适应降速；连续 5 次连接失败熔断中止本域（避免延长封禁）
- **1000 页的站点约需 5.5 分钟**：`3 req/s × 1000 页 ≈ 333 秒` 是墙钟下界，实测 382 秒中 87% 花在等待限速。**增加并发无法缩短**——限速器按墙钟串行放行。这是设计取舍，不是性能缺陷
- 实测 `docs.python.org` 抓取 1000 页：382 秒，991 成功 / 9 失败，中断后可续跑

## 部署

```bash
docker compose up -d        # 默认仅绑定 127.0.0.1:8000
```

- **Dockerfile**：非 root 运行、依赖层缓存、健康检查探活 `/api/v1/health`
- **docker-compose.yml**：数据卷、日志轮转（防磁盘写满）、SQLite/PostgreSQL 可切换
- **render.yaml**：Render 免费版一键部署（含免费版限制说明与默认降配）
- **上线前验收**：`./tools/guard_smoke.sh` —— 11 个用例实测 SSRF、限流、并发、黑名单四道闸。**单测全绿不代表容器里的闸活着**

完整选型与成本测算见 **[DEPLOY.md](DEPLOY.md)**（实测数据：CPU 非瓶颈、峰值内存约 100 MB、镜像 438 MB）。

## 架构

```
backend/seoclaw/
├── crawler.py       BFS 抓取：限速 / 自适应降速 / 熔断 / 代理轮换 / 断点续传
├── extract.py       HTML → Page（trafilatura 正文抽取）
├── audit/
│   ├── engine.py    规则执行 + 站点级事实（覆盖率、hit_page_limit）
│   └── rules/       base / google / baidu / cnh_eco / geo
├── keywords/        关键词扩展 + 聚类（纯离线，无需 API key）
├── brief.py         内容 Brief 生成
├── llm.py           可选 LLM 总结（OpenAI 兼容协议，0 新增依赖）
├── db/              12 表 + Alembic 迁移
├── report.py        Markdown 报告
├── report_html.py   单文件 HTML 报告
├── web/             在线体检页（quick-scan + 进度轮询）
├── api/             FastAPI 服务层（鉴权 / 额度 / 归属验证）
└── mcp_server.py    MCP Server（3 个只读工具）
```

**约 14,400 行实现代码 · 约 8,850 行测试代码 · 618 个测试（617 通过 / 1 跳过）。**

### 数据库

12 张表：`sites` / `crawl_jobs` / `pages` / `issues` / `keywords` /
`serp_snapshots` / `content_briefs` / `suggestions` / `api_keys` /
`rank_alert_acks` / `usage_events` / `rank_history`。

```bash
cd backend && alembic -c migrations/alembic.ini upgrade head
```

> ⚠️ 上线**必须走 Alembic 迁移**。`create_all` 只保证空库能启动，**不会为已有库补新列**——混用会制造「测试正常、生产 500」的静默故障。

## 开发与测试

```bash
git clone https://github.com/Geek0ne/SEOClaw.git
cd SEOClaw
pip install -e ".[api,dev]"
pytest backend/tests -q
```

### 测试

- **618 个测试**：617 通过、1 跳过（`mcp` 为可选依赖，安装 `mcp` extra 后全量运行）
- 覆盖率约 82%（CI 门禁 78%，为波动留余量）
- **CI 双任务**：① 全量测试 + 覆盖率 + CLI 冒烟 + wheel 构建；② `guard_smoke.sh` 真容器验收（四道闸）
- 部分环境用 `run.sh` 封装本机依赖安装方式（`.deps/` 隔离 + `PYTHONPATH`），见脚本内注释

## 相关文档

| 文档 | 内容 |
|---|---|
| [DEPLOY.md](DEPLOY.md) | 部署选型与成本实测 |
| [DESIGN.md](DESIGN.md) | Web 界面设计系统（唯一事实来源） |
| [REQUIREMENTS.md](REQUIREMENTS.md) / [PLAN.md](PLAN.md) | 产品需求与演进规划 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南与新增规则的门槛 |
| [SECURITY.md](SECURITY.md) | 安全政策与攻击面说明 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

## 设计原则

以下约束由实测教训固化而来，是代码层面的硬规矩：

1. **只报有正面证据的问题**——「未检出」推不出「不存在」
2. **覆盖率不足时，站点级规则必须沉默**
3. **报告必须列出未审到的页面**——避免读者把「没审成」理解为「没问题」
4. **无付费数据源时，搜索量字段留 `null`**，不填 0
5. **`--db` 未指定时不落库**——不主动为用户创建数据库文件
6. **落库失败不得让报告消失**——增强层故障不拖垮主结果
7. **实验性规则与已验证规则物理隔离**——`geo` 包需显式启用

## 路线图

当前版本聚焦「技术 SEO 审计」的准确性与可交付性。规划中的方向（详见 `REQUIREMENTS.md` / `PLAN.md`）：

- SERP 排名与流量监测、异动告警
- 竞品追踪与内容缺口分析
- 内容日历与批量 Brief
- 一键导出 PR diff / PDF / Excel

## License

MIT
