<div align="center">

# SEOClaw

**只说实话的站点 SEO 体检工具**

107 个真实站点实测 · 严格准确率 97.0% · 误报从 31 条压到 7 条

`pip install seoclaw` → `seoclaw scan example.com`

许可证 MIT

</div>

---

## 它解决的问题

SEO 工具的典型输出是**一张 200 行的红字清单**。你收藏了它，然后再也没打开过——因为没人告诉你该先动哪一条。

更糟的是：清单里的**误报会主动伤害你**。你照着一条「危险：屏蔽百度收录」去改，结果那是论坛自己的策略选择，改完流量归零。

SEOClaw 的取舍正相反：**宁可漏报，不报假的。**

| | 典型 SEO 工具 | SEOClaw |
|---|---|---|
| 规则触发门槛 | 「我没找到」即报缺失 | 必须有**正面证据**，否则沉默 |
| 站点级规则 | 无论覆盖率一律报 | 覆盖率不够直接**闭嘴** |
| 抓取失败 | 不提，报告看起来完整 | 明确列出**没审到的页面** |
| 搜索量 | 填 0（暗示真的没人搜） | 拿不到数据就**留空** |
| 准确率 | 厂商自述，不公开方法 | **公开 107 站逐条回源核对结果** |

---

## 准确率是被验证过的

`严格准确率 97.0%` 不是营销词，是一个可以复现的数字：

- **样本**：107 个真实站点 —— 博客 / 电商 / 文档站 / 政府站 / 中文社区 / 大型企业站
- **方法**：逐条开浏览器**回源核对**，不是看它说得像不像，是看它说得对不对
- **结果**：报告 723 条 → 可判定 530 条 → 属实 514 → 噪音 9 → **真误报 7**

站点数从 23 扩到 107，是因为前两轮**静默丢了 18 站**——而那批恰恰是反爬 / JS 渲染 / 畸形 sitemap 最容易暴露的。**删掉难样本的高准确率不能报。**

### 7 条误报是怎么压掉的

每一条都留了实跑证据，不是改阈值改到不报为止：

| 规则 | 现象 | 根因 | 修法 |
|---|---|---|---|
| `title.too_short` | 首页 `Home \| gov.sg` 被判过短 | 规则的立论只对**参与关键词竞争的内容页**成立 | 按 URL 形态豁免（`/` `/login` `/terms`…），不靠 title 字面猜 |
| `title.missing` | Agoda 首页被判无 title | 静态 HTML 里没有，但那是 **JS 注入的** | 引入提取层实测的 `likely_js_rendered` |
| `robots.baiduspider_not_allowed` | 非中文站屏蔽百度被判危险 | 那是站方的**主动选择** | 降级 INFO + `verdict: possibly_intentional` |
| `title.chinese_too_long` | Discourse 中文标题过长 | crawler 带 `Accept-Language: zh-CN`，接了翻译的站**把整页机器翻译**后再返回 | 识别翻译视图，作者改不了的东西不报 |

还有两条 agent 当初判断**错了**，我用实跑推翻了：

- `h1.missing`：直接 grep 原始 HTML，arxiv / bellroy **确实一个 h1 都没有**，规则判对了
- `title.pixel_overflow`：Discourse 中文标题估算 708px vs 阈值 580px，误差带下界仍越界，**该报**

---

## 安装

```bash
pip install seoclaw
```

Python 3.11+。无需配置。

```bash
seoclaw scan example.com                    # 报告打到屏幕
seoclaw scan example.com -o report.md       # Markdown
seoclaw scan example.com --html out.html     # 单文件 HTML，可直接发客户
seoclaw rules                                # 看看会查些什么
```

### 常用参数

| 需求 | 参数 |
|---|---|
| 中文站专项检查 | `--market baidu` |
| 多站批量、趋势对比 | `--db seo.db` |
| 中断续跑 | `--checkpoint ./ck` |
| Vue / React 站点 | `--render-js` |
| 被限流了 | `--proxy-file proxies.txt` |
| 增量扫描（ETag/304） | `--incremental --checkpoint ./ck` |

---

## 规则覆盖

**默认 39 条**（28 页面级 + 11 站点级），覆盖 title / description / H1 / canonical /
noindex / 图片 alt / 内链锚文本 / 软 404 / 结构化数据等。

按需加载的市场包：

| 包 | 市场 | 条数 | 命令 |
|---|---|---|---|
| `google` | Google | 5 | `--market google` |
| `baidu` | 百度 | 5 | `--market baidu` |
| `cnh_eco` | 微信搜狗 | 1 | `--market cnh_eco` |
| `geo` | AI 搜索引用性 | 4 | `--market geo` |

> **`geo` 包默认不加载。** 这 4 条的证据强度明显弱于 base——base 的 39 条在
> 107 站上验到 97.0%，geo 还没有同等验证。混在一起会拖累已经验过的规则。

### 有意为之的「沉默」

以下情况工具**故意不报**，因为报了就是错的：

- 站点主动屏蔽搜索引擎收录 → 标 `possibly_intentional`，INFO 级
- 覆盖率不足时的站点级规则（「我没发现内链」推不出「它没有内链」）
- JS 渲染页面的静态检查项
- 可能是有意为之的关键词堆砌 / 低质量标题

---

## Web 版

```bash
uvicorn seoclaw.main:app --port 8000
```

打开浏览器输网址就能用，无需安装。扫描在后台跑，页面轮询进度——
**不会让浏览器转圈等一分钟**。

---

## 对第三方站有多客气

默认 **3 req/s**，遵守 `robots.txt` 与对方声明的 `Crawl-delay`。遇 429/403
自动降速，连续 5 次连接失败直接熔断中止本域——对方在按 IP 拉黑时，
继续打只会让封禁更久。

由此产生一个**必须说清楚的硬限制**：

> 1000 页的站要扫 **5 分半，不是 5 分钟**。
> 限速 `3 req/s × 1000 页 = 333 秒` 是墙钟下界，实测 382 秒里 87% 花在等限速。
> **加并发压不下去**——限速器按墙钟串行放行。
> 这是「对第三方站有多客气」的设计取舍，不是性能 bug。

实测 `docs.python.org` 抓 1000 页：**382 秒**，991 成功 / 9 失败，无崩溃，
中断后续跑正常接上。

---

## 架构

```
backend/seoclaw/
├── crawler.py       BFS 抓取：限速 / 自适应降速 / 熔断 / 代理轮换 / 断点续传
├── extract.py       HTML → Page（trafilatura 正文抽取）
├── audit/
│   ├── engine.py    规则执行 + 站点级事实（覆盖率、hit_page_limit）
│   └── rules/       base / google / baidu / cnh_eco / geo
├── keywords/        关键词扩展 + 聚类（纯离线，不需要任何 API key）
├── db/              9 表 + Alembic 迁移（枚举降级为 VARCHAR+CHECK）
├── report.py        Markdown 报告
├── report_html.py   单文件 HTML 报告
├── web/             在线体检页（quick-scan + 轮询）
└── api/             FastAPI 服务层
```

**11,700 行代码 · 7,388 行测试 · 522 个测试全绿。**

### 数据库

9 张表：`sites` / `crawl_jobs` / `pages` / `issues` / `keywords` /
`serp_snapshots` / `content_briefs` / `suggestions` / `rank_history`。

```bash
cd backend && alembic -c migrations/alembic.ini upgrade head
```

> ⚠️ 上线**必须走 Alembic**。`create_all` 只保证空库能起来，**不会给已有库补新列**——
> 混用会造出「测试里正常、生产直接 500」的静默故障。

---

## 写在代码里的几条硬规矩

这些不是风格偏好，是踩过坑之后钉死的：

1. **只报有正面证据的**。「我没搜到」推不出「它没有」。
2. **覆盖率不够时站点级规则必须沉默。**
3. **报告必须列出没审到的页面。** 否则读者会把「没审成」理解成「没问题」。
4. **没有付费数据源时搜索量留 `null`**，不填 0。
5. **`--db` 不给时不落库。** 悄悄给用户建数据库文件是侵入行为。
6. **落库失败不能让报告消失。** 增强层坏掉不该把主结果一起拖下去。
7. **实验性规则与已验证规则物理隔离。** GEO 包要显式开启，正是这条。

---

## 开发

```bash
git clone https://github.com/Geek0ne/SEOClaw
cd SEOClaw
pip install -e ".[dev,api]"
pytest backend/tests -q
```

---

## License

MIT
