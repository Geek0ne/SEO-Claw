# AI SEO Agent — 执行计划（PLAN）

版本：v1.0
日期：2026-09-29
目标：**真做产品**，不是 Demo。每一阶段都以"可交付给真实用户"为验收标准。

---

## 0. 阶段定义与核心原则

### 阶段划分（4 个里程碑）

| 里程碑 | 周期 | 交付物 | 验收标准（可验证） |
|---|---|---|---|
| **M0 内核** | 2 周 | 爬虫 + 规则引擎 + 20 项检查 + CLI 报告 | 真实站点跑出报告，规则人工核对准确率 ≥90% |
| **M1 产品** | 4 周 | Web 应用 + 站点管理 + 报告 UI + API | 外部用户能自助接入站点并拿到价值 |
| **M2 智能** | 4 周 | 关键词 + 内容 Brief + 改写 + 竞品 | AI 产出的 Brief 被人工评审通过率 ≥70% |
| **M3 商业** | 6 周 | 多租户 + 计费 + 监控 + 插件 | 首个付费转化 |

### 四条铁律

1. **无黄金样本不动 LLM Prompt** —— 每次改 Prompt 必跑 `tests/golden/`，回归掉了就回滚
2. **规则检查项永不依赖 LLM** —— 60+ 技术检查全是确定性规则，LLM 只做策略与内容
3. **写操作默认只读** —— 所有"修改"产出 diff/PR，需人工确认，保留回滚点
4. **每个里程碑必须能被非开发者使用** —— CLI 也算，但必须产出人能读懂的东西

---

## 1. M0 内核（第 1-2 周）— 最核心，现在就做

### 为什么先做这个
产品价值 = 检查项准不准 × 建议能不能落地。M0 把这两件事的地基打好，后面全是扩展。

### 1.1 本周任务拆解

| 天 | 任务 | 产出 |
|---|---|---|
| D1 | 领域模型 + 数据库 schema | `models/` + Alembic 首个迁移 |
| D2 | HTML 提取层（title/meta/h1/canonical/正文/Schema/图片/链接） | `extract/` 可用 |
| D3-4 | 规则引擎 + 20 项通用检查 | `audit/engine.py` + `rules/base/` |
| D5 | 爬虫调度器（frontier 队列、限速、断点续传、robots） | `crawler/` |
| D6 | 健康分 + 优先级排序 | `scoring/` |
| D7 | CLI + Markdown 报告 | `seo scan <url>` 出报告 |

### 1.2 核心设计要点

**爬虫调度器**
```
Frontier（Redis List，支持优先级）
  → 取 URL → robots 检查 → 同域去重 → 抓取
  → 解析 → 提取结构 → 存 Page
  → 发现新链接（same-domain）→ 依限速策略入队
断点续传：已抓 URL 存 Redis SET，进程重启后自动跳过
并发：单域默认 3 req/s（可配），全局 20 req/s
失败重试：3 次指数退避，超出入死信
```

**规则引擎**
```python
class Rule(ABC):
    code: str              # 唯一标识，如 "title.missing"
    market: str            # base / google / baidu / cnh_eco
    severity: Severity     # critical / high / medium / low / info
    scope: Scope           # page / site
    def check(self, page: Page, ctx: RuleContext) -> list[Issue]: ...
```
- 规则注册表按 market 自动加载
- 每条 Issue 必须带**证据**（evidence 字段）：具体字段值 + 来源
- 同一 code 同一 URL 只保留最高 severity

**健康分算法（初版）**
```
总分 = 100
扣分 = Σ(weight[severity] × affected_pages_ratio)
  critical: 30 / high: 15 / medium: 5 / low: 1
按模块分组给分，另给 6 维雷达（可抓取性/信息架构/页面质量/性能/结构化数据/信任）
```
> 权重后续必须用真实数据校准，不能拍脑袋长期用。

**M0 首批 20 项检查（全部 base 通用包）**

| # | code | severity | 检查逻辑 |
|---|---|---|---|
| 1 | `title.missing` | critical | title 标签缺失或空白 |
| 2 | `title.duplicate` | high | 同站 title 完全重复（>2 个页面） |
| 3 | `title.too_long` | medium | 英 >60 字符 / 中 >30 字符 |
| 4 | `title.too_short` | low | <15 字符 |
| 5 | `meta.missing` | high | meta description 缺失 |
| 6 | `meta.duplicate` | medium | 同站完全重复 |
| 7 | `h1.missing` | high | 无 H1 |
| 8 | `h1.multiple` | medium | 多于 1 个 H1 |
| 9 | `canonical.missing` | medium | 无 canonical |
| 10 | `canonical.conflict` | high | canonical 指向非自身/跨域 |
| 11 | `noindex.present` | critical | 页面有 noindex 但被收录 |
| 12 | `img.alt.missing` | medium | 图片无 alt |
| 13 | `img.alt.generic` | low | alt 是 "image"/"图片" 等无意义值 |
| 14 | `link.broken` | critical | 内部链接返回 4xx/5xx |
| 15 | `link.noanchor` | medium | 内部链接锚文本为空 |
| 16 | `depth.excessive` | medium | 点击深度 >4 层 |
| 17 | `orphan.page` | high | sitemap 存在但无内链指向 |
| 18 | `http.mixed_content` | high | HTTPS 页内含 http 资源 |
| 19 | `schema.missing` | low | 无任何结构化数据 |
| 20 | `soft404` | high | 页面内容极少（<300 字）且返回 200 |

### 1.3 M0 验收清单（硬性）
- [ ] 抓 1000 URL 不崩，进程重启能续跑
- [ ] 20 项规则在 20 个真实站点上人工核对，准确率 ≥90%
- [ ] 报告能给出"Top 5 优先做"且每条有可执行改法
- [ ] 遵守 robots.txt，单域限速生效
- [ ] 一次全站扫描 ≤5 分钟（1000 URL）

---

## 2. M1 产品化（第 3-6 周）

- **D8-9**：数据库 schema 完整落地 + Alembic + repository 层
- **D10-12**：FastAPI + 站点管理 API + 鉴权（单租户先）
- **D13-16**：Next.js 前端 7 个核心页面 + 设计系统落地
- **D17-18**：站点接入流程（输网址 → 扫描 → 进度 → 报告）
- **D19-20**：报告 UI（问题列表、证据展示、修复代码块）+ 一键复制

**验收**：外部用户自己注册 → 接入站点 → 10 分钟内拿到可信报告

---

## 3. M2 智能化（第 7-10 周）

- 关键词扩展与聚类（jieba + pgvector）
- SERP 抓取与拆解（SerpAPI/DataForSEO）
- 内容 Brief 生成（instructor 结构化输出）
- 页面改写（Title/Meta/H1/正文/FAQ）
- 竞品识别（SERP 重合度）
- **GEO/AI 搜索可引用性评估**（差异化重点）

**验收**：Brief 人工评审通过率 ≥70%

---

## 4. M3 商业化（第 11-16 周）

- 多租户 + RBAC + 团队协作
- 计费与额度
- 排名监控与告警
- WordPress / Shopify 插件
- MCP Server

---

## 5. 风险登记册

| 风险 | 概率 | 影响 | 缓解 | 触发后动作 |
|---|---|---|---|---|
| 规则误报率高 | 高 | 高 | 黄金样本回归 + 置信度阈值 | 低于阈值只做提示不做告警 |
| 抓取被封 IP | 中 | 中 | 限速 + robots + UA 声明 | 加 IP 池 |
| LLM 成本失控 | 中 | 高 | 缓存 + 分层模型 + 预算熔断 | 按站点设日限额 |
| 大站扫描超时 | 中 | 中 | 优先级队列 + 增量扫描 | 分片 + 断点续跑 |
| 第三方 API 涨价 | 中 | 中 | Provider 抽象层 | 换供应商 |
| 竞品（大厂）下场 | 低 | 高 | 死磕 GEO + 执行闭环 | 转向垂类 |

---

## 6. 质量保障

| 项 | 工具 | 门槛 |
|---|---|---|
| 格式/静态检查 | ruff | 零告警 |
| 类型检查 | mypy strict | 零错误 |
| 单元测试 | pytest | 核心规则 100% 覆盖 |
| **黄金样本回归** | 自建 | **改动 Prompt 必跑，通过率不得下降** |
| 集成测试 | 真实站点快照 | M0/M1 各一次全量 |

---

## 7. 当前状态

- [x] 需求规划书（REQUIREMENTS.md）
- [x] 执行计划（本文档）
- [x] M0 代码骨架：模型 / 提取 / 爬虫 / 规则引擎 / 评分 / 报告 / CLI
- [x] 22 条检查项（base 包）
- [x] Sitemap 发现与播种
- [x] 黄金样本回归测试（48 个用例，含渲染层）
- [x] 爬虫加固：自适应降速 / 连续失败熔断 / Crawl-delay
- [x] 误报治理第一轮（link.noanchor 28→0，soft404 分级，canonical 回访）
- [x] 报告展示：判定依据（verdict）置顶，不再被截断
- [ ] 待定：真实练手站点（需多站样本做准确率校准）

## 8. 待办清单（按优先级）

### P0 — 阻塞 M0 验收

| # | 事项 | 说明 | 状态 | 预估 |
|---|---|---|---|---|
| 1 | **误报率下降** | 目标 ≥90%。23 站真重抓：**96.9%，真误报 0**（可判定 128 条中属实 124、属实但噪音 4）。已修：link.noanchor 提取层、canonical 大小写自引用降 INFO、h1.multiple 只在内容完全重复时报（噪音 10→0）、错误页面的 noindex 不再报 CRITICAL。另修掉核对器自身 3 处误判 | ✅ 已完成 | — |
| 2 | **多站人工核对** | 23 站（博客/电商/文档/政府/中文社区）自动回源核对，核对了规则 16 条 | ✅ 已完成 | — |
| 3 | **评分权重校准** | **有结论：权重不动。** 用 29 站 × 25 页重抓（601 页）验证——受影响面 r 的中位数降到 0.04~0.12，全站命中的只剩 0~11%，不再被 5 页样本下 0.2 整数倍的量化绑架。现权重 30/15/5 在这个粒度下表现合理，**原判断被数据证实，故不改**。之前「阻塞」的理由是样本量，样本量补上后原判断就成立了，不需要硬凑一个校准动作 | ✅ 已完成（结论：不改） | — |
| 4 | **报告文案审校** | 扫 37 条 rule 文案，判决性措辞 0 处。h1.multiple 的文案自相矛盾已随规则一并修掉 | ✅ 已完成 | — |
| 5 | **审计范围（追加）** | 实测 gymshark.com 抓 25 页有 24 页是 `us.checkout.gymshark.com`，124 条问题 119 条来自子域，主站被判 0.0 分。结账页带 noindex 是**正确配置**，却报成 CRITICAL「页面被屏蔽收录」——规则判得对、用户照做反而更糟。已新增 `same_site_scope()`：host 相同或仅差 www 才算本站（不能复用 `is_internal()`，它按可注册域判断，对内链权重传递才是对的）；分母也改为本站实抓页数 | ✅ 已完成 | — |

### P1 — M1 产品化前置

| # | 事项 | 说明 |
|---|---|---|
| 5 | 数据库与持久化 | 当前全内存 + 磁盘 checkpoint。需 PostgreSQL schema + Alembic，页面结果落库才能做增量扫描与历史趋势 |
| 6 | FastAPI 服务层 | 站点管理、扫描触发、报告查询三类接口 |
| 7 | 增量扫描 | 内容 hash 未变的页面跳过检测，只更新 `fetched_at` |
| 8 | 代理 IP 轮换 | 云 IP 被目标站封禁已是常态，商业化必须支持 |
| 9 | Google 规则包 | Search Console 覆盖率、移动优先索引、CWV、hreflang |
| 10 | 百度规则包 | 收录率、Baiduspider 单独策略、ICP、移动适配 |

### P2 — M2 智能层

| # | 事项 | 说明 |
|---|---|---|
| 11 | LLM 适配层 | litellm + instructor 封装，先做「报告 AI 总结」验证链路 |
| 12 | 关键词扩展与聚类 | jieba 分词 + pgvector 语义聚类 |
| 13 | 内容 Brief 生成 | 目标词、意图、Top10 共性、差异化机会 |
| 14 | GEO / AI 搜索可引用性 | 差异化重点，需先做方法论验证 |

## 9. 已知技术债

- **断点续传会丢页面数据**：visited 集合持久化了，但已抓页面的解析结果没存，重启后这些页面会被跳过且无数据。DB 落地后修复。
- **孤岛页检测依赖覆盖率**：`hit_page_limit` 时一律不下结论，即使已抓 1000 页。建议 M1 加「分批跑完整个站点」的扫描模式。
- **CJK 判定用字符范围**：`_is_cjk` 只看 U+4E00–U+9FFF，漏了日文假名与韩文。中文站够用，多语言站需改用 Unicode 脚本属性。
- **单页解析失败降级为 `error` 字段**：该页跳过所有规则审计，但报告里不体现「这个页没审成」。应单独出一类问题。
