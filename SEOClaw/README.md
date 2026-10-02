# SEOClaw

一个**开源的站点 SEO 体检工具**：抓一遍站点，跑规则，出一份能照着改的报告。

> 目标不是「告诉你有多少问题」，而是「告诉你**先改哪三个**」。

---

## 它解决什么

大多数 SEO 工具扫完给你一张 200 行的清单，你不知道从哪下手。
这个工具的三条设计原则：

1. **只报能改的**。规则要么有正面证据（页面里确实写着 `noindex`），要么有站点级覆盖率兜底。「我没搜到」推不出「它没有」——所以宁可沉默。
2. **诚实标注数据充分性**。覆盖率不够、页面抓取失败、frontier 没排空，这些都会**显式写进报告**，而不是让一份残缺的数据看起来像「没问题」。
3. **误报比漏报更贵**。一条错报会让用户去改本来正确的地方，改完更糟。所以规则宁可降级为 INFO 并标注「可能是有意为之」，也不硬报。

---

## 快速开始

```bash
pip install -r requirements.txt

# 扫一个站，输出 Markdown 报告
PYTHONPATH=backend python3 -m app.cli scan https://example.com --max-pages 100 -o report.md

# 看有哪些规则
PYTHONPATH=backend python3 -m app.cli rules
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--market google\|baidu\|cnh_eco` | 加载对应生态的规则包，可重复 |
| `--db seo.db` | 结果落库（页面 / 问题 / 关键词），默认只出报告 |
| `--checkpoint ./ck` | 断点续传：中断后重跑会接着上次继续 |
| `--rps 3.0` | 单域每秒请求数，**别调高**（见下方「礼貌」一节） |
| `--incremental` | 带 ETag/Last-Modified 条件请求，304 的页跳过规则重跑 |
| `--render-js` | 对疑似 SPA 空壳页执行 JS 渲染（慢 10~50 倍） |
| `--html report.html` | 生成单文件 HTML 报告，无外链、可直接发客户 |
| `--proxy` / `--proxy-file` | 被 403/429 封禁时自动轮换出口 |

---

## 规则包

| 包 | 市场 | 条数 | 加载方式 |
|---|---|---|---|
| `base` | 通用 | 39 | 默认 |
| `google` | google | 5 | `--market google` |
| `baidu` | baidu | 5 | `--market baidu` |
| `cnh_eco` | cnh_eco | 1 | `--market cnh_eco` |
| `geo` | 通用 | 4 | **默认不加载**，需显式开启 |

### 为什么 GEO 包默认不加载

AI 搜索可引用性（`geo`）这 4 条规则，**证据强度明显弱于 base 包**——
base 的 39 条在 107 个真实站上验到 97.0% 严格准确率，geo 还没有这个级别的验证。

混在一起会让好规则一起被拖下水。要用请显式 `--market geo`。

---

## 准确率

**107 个真实站点**（博客 / 电商 / 文档 / 政府 / 中文社区 / 大型企业站）全量回源核对：

```
严格准确率 97.0%
报告 723 条 / 可判定 530 / 属实 514 / 噪音 9 / 真误报 7
真误报从 31 条降到 7 条
```

站点数从 23 扩到 107，是因为前两轮静默丢了 18 站——
而那批恰恰是反爬 / JS 渲染 / 畸形 sitemap 最容易暴露的，
**删掉难样本的高准确率不能报**。

---

## 性能

实测 `docs.python.org` 抓 1000 页：**382 秒**，991 成功 / 9 失败，无崩溃，16 页处 kill 后续跑正常接上。

⚠️ **单站 1000 URL 压进 5 分钟在当前架构下做不到。**
限速器 `per_domain_rps=3.0` 意味着单页最小间隔 0.333s，
1000 页的**墙钟下界是 333 秒**（占实测 382s 的 87%），本身就超过 300 秒目标。
限速器按墙钟串行放行，**加多少并发都压不下去**。
这是「对第三方站有多客气」的设计取舍，不是性能 bug。

---

## 礼貌

- 默认 **3 req/s**，遵守 `robots.txt` 与 `Crawl-delay`
- 遇 429/403 **自动降速**，连续 5 次连接失败直接熔断中止本域
  （对方在按 IP 拉黑时，继续打只会让封禁更久）
- **`--ignore-robots` 只用于你自己的站点**

---

## 架构

```
backend/app/
├── crawler.py      BFS 抓取：限速 / 自适应降速 / 熔断 / 代理轮换 / 断点续传
├── extract.py      HTML → Page（trafilatura 正文抽取）
├── audit/
│   ├── engine.py   规则执行 + 站点级事实（覆盖率、hit_page_limit）
│   └── rules/      base / google / baidu / cnh_eco / geo 五个规则包
├── keywords/       关键词扩展 + 聚类（纯离线，不依赖任何 API key）
├── db/             9 表 + Alembic 迁移（枚举降级为 VARCHAR+CHECK）
├── report.py       Markdown 报告
├── report_html.py  单文件 HTML 报告
├── api/            FastAPI 服务层
└── persist.py      CLI 与 API 共用的落库逻辑
```

**约 11500 行应用代码 / 7100 行测试，505 个测试全绿。**

### 数据库

9 张表：`sites` / `crawl_jobs` / `pages` / `issues` / `keywords` /
`serp_snapshots` / `content_briefs` / `suggestions` / `rank_history`。

```bash
cd backend
PYTHONPATH=.. alembic -c migrations/alembic.ini upgrade head
```

⚠️ 上线**必须走 Alembic**。`create_all` 只保证空库能起来，
**不会给已有库补新列**——两者混用会造出「测试里正常、生产直接 500」的静默故障。

---

## API

```bash
PYTHONPATH=.deps:backend DATABASE_URL=sqlite+aiosqlite:///./seoclaw.db \
  python3 -m uvicorn app.main:app --port 8000
```

7 个端点：健康检查 / 站点 CRUD / 扫描触发 / 任务查询 / 问题查询 / 报告。

---

## 设计上的几条硬规矩

这些不是风格偏好，是踩过坑之后钉死的：

- **覆盖率不够时站点级规则必须沉默**。「我没发现指向它的内链」只有在确信「大部分页面都看到了」时才成立。
- **报告必须列出「没审到的页面」**。引擎整页跳过时，若报告不提，读者会把「没审成」理解成「没问题」。
- **没有付费数据源时搜索量留 `null`，不填 0**。填 0 等于宣称「这个词搜索量真的是 0」。
- **`--db` 不给时不落库**。悄悄给用户建个数据库文件是侵入行为。
- **落库失败不能让报告消失**。增强层坏掉不该把主结果一起拖下去。

---

## License

MIT