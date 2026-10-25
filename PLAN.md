# SEO-Claw — 执行计划（PLAN）

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
- [x] 抓 1000 URL 不崩，进程重启能续跑 —— 实跑 docs.python.org 1000 页：382s 完成、991 成功/9 失败、无崩溃；16 页处 kill 后续跑正常接上
- [x] 22 项规则在 **107** 个真实站点上回源核对，严格准确率 **97.0%** ≥90%（原先只要求 20 站，实际做到 107 站全集）。
  口径说明：93.3% 是**只跑 base 包**的旧数字；97.0% 是 base+google+baidu+cnh_eco 全市场实跑（v7，报告 723 条 / 可判定 530 / 存疑 193 / 属实 514 / 噪音 9 / 真误报 7）
- [x] ~~一次全站扫描 ≤5 分钟（1000 URL）~~ **该指标于 2026-10-22 作废（决策③）**。
  实测 382s（6.4 分钟）超原线，但归因早已查明：限速器 `per_domain_rps=3.0`
  → 单页最小间隔 0.333s，1000 页的**墙钟下界是 333s**（占实测 87%），
  串行放行，**加多少并发都压不下去**；并行化最多再省 ~49s → 333s，仍差 33s。
  达标只剩「默认 rps 提到 ≥3.34」一条，代价是对第三方站更激进、被封概率上升。
  **决策：保持 3 rps 不动，把这条从「性能指标」降级为「实测事实」**——M0 真正
  要的两项（不崩、重启能续跑）已由上面第一条覆盖，5 分钟这个数字当初是拍的，
  而礼貌上限是真实约束。今后引用性能口径请说「1000 URL ≈ 6.4 分钟（3 rps
  礼貌上限下的物理结果）」，不要再说「应该 5 分钟」。
- [x] 报告能给出"Top 5 优先做"且每条有可执行改法 —— **2026-10-21 验证通过**。
  真站实测 antfu.me（5 页 / 13 问题）：Top 5 全部带 fix_hint/fix_example；
  并补齐了出口缺口：CLI `--json`、API `/report`（Web+MCP）此前**拿不到**
  Top 5（网页还在自己按严重级排序，与报告的「严重度 × 影响面」口径
  分叉）——现已统一由 `scoring.top_actions` 服务端装配（阶段 3）
- [ ] 遵守 robots.txt，单域限速生效 —— 部分已验（lobste.rs 的 `Disallow: /` 被正确遵守，0 页）
- ~~一次全站扫描 ≤5 分钟（1000 URL）~~（本清单原有的重复条目，已随决策③作废，见上）

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

| 项 | 状态 |
|---|---|
| 排名监控与告警 | ✅ 2026-10-04 完成。`alerts.py` 只做判断不碰 DB（因此能离线测边界，5 个「沉默侧」用例），三道门槛（min_drop / min_impressions / min_days）由调用方显式传入 —— 「多吵才算吵」是场景的事不是代码的事。`position=None` 是「当天没排名数据」而非「排最后」，拿它算差值会静默返回空列表，把「无法判断」伪装成「没有跌落」。⚠️ 2026-10-18 补数据入口：此前表与判断器就绪但**没有任何路径能把数据灌进去**，监测是个只能看的空壳。现补 `rankdata.py`（CLI `rank-import` + `POST /rankings`，坏行逐行报错、区间聚合拒收），闭环才真正通 |
| MCP Server | ✅ 2026-10-04 完成。三个**只读**工具；工具集即权限边界，故测试里有一条反向用例：工具名含 delete/update/create 即红。报告装配复用 `api/summary.py` 与 HTTP 端点同一份 —— 两处口径分叉意味着模型给的建议会和用户看到的对不上。⚠️ 依赖 mcp 2.x（`FastMCP` 已改名 `MCPServer`） |
| 计费与额度 | 🟡 **只做了计量半**。`usage_events` 追加写 + 幂等键 `(kind, ref_id)` + `SUM` 汇总。**不做就地累加** —— 任何重试都会让数字对不上且事后无法自证；**重复计量比漏计量严重得多**。⚠️ 定价与配额阈值**未做**：那是产品决策，需产品负责人定。✅ **2026-10-22 定性：API Key 这套保留**（只存哈希 + 签发/撤销 + 额度 + 用量事件 + 站点归属验证），它是《商业模式方案》模式二原文点明「不用改内核，只加鉴权和配额」的那两项，也是企业版溢价项「API 访问权限」的实现——缺的是**定价映射**（¥0.5–2/页 或 ¥99/¥399/¥999 档位 → 阈值），不是新机制 |
| 托管定时复扫 | ✅ 2026-10-20 完成（改造阶段 2b）。到期自动入队走持久队列，CAS 认领多 worker 不双扫；语义见 CHANGELOG「阶段 2b」。最小间隔 1 小时；失败不影响下轮调度 |
| 多租户 + RBAC + 团队协作 | ⬜ **未做。2026-10-22 依两份商业文档定了推进节奏**（此前「卡决策」的球部分回到我们脚下）：**第一步不是 RBAC，是「账号-站点归属 + 数据隔离」的最小闭环**——《商业模式方案》建议 0–6 个月只跑模式一（¥99/¥399 两档，1 站/3 站自用），这两档没有多人协作也够用；《产品手册》里 RBAC、操作审计、私有部署是**企业版与定制企业版**的承诺，那一档排在 12 个月+。真正的触发点是手册「增值服务」那条**团队协作 +¥20/月/席位**：出现第二个付费席位时再引入 owner/editor/viewer，而不是提前建一套没人用的角色表。已有地基：`site_id` 已是各表外键且 `ON DELETE CASCADE`，API Key 已按 key 隔离额度与用量。⚠️ **文档超前于实现的三处**（对外销售前要么补齐要么改口径）：手册承诺「基于 RBAC 的细粒度权限管理」现在**没有**；「完整的操作日志与访问审计」现在只有 `usage_events`（计量用途，非审计用途）；「敏感信息（如 API 密钥）采用 AES-256 加密」与实现不一致——实现是**只存哈希**（不可逆，比加密更强，代价是明文只在签发那一次返回）。加密能回读、哈希不能，这句得有人认 |
| WordPress / Shopify 插件 | ⬜ **未做，卡决策**。需先定插件形态（只读报告展示 vs 双向同步 vs 一键修复） |

> ⚠️ 上面「未做」的项**不是活儿不足，是等决策或等收入**。2026-10-22 一轮拍板后：多租户/RBAC 的**推进节奏**已定（见上，触发点是第二个付费席位），仍待的是「何时真有团队版需求」；API 制定价阈值、WordPress/Shopify 插件形态、SERP 代抓（明确延后到盈利后）三件仍在产品负责人那边。

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

- [x] **Web 界面改版三轮（2026-10-25）：v2 深色 → v3 亮色商务 → v3.1 大气版**。
  第一轮 v2「Claw Noir」（深色）当日被要求改亮色大气商务风（v3「Daylight」：
  纸白 + 点阵网格 + 白卡双层软阴影 + 珊瑚品牌色 + 彩色线性图标方标
  `decorateIcons()` + SEV 数字着色）；随后产品负责人指出「三个菜单像小作坊」，
  v3.1 升级为**产品级信息架构**：顶栏主导航（4 项 + 系统状态灯 + API 钥匙
  入口，sticky 毛玻璃）、左栏收窄为站点工作区、仪表盘改为**指挥中心**
  （聚合指标 4 枚 + 产品能力矩阵 6 格 + 站点卡片网格，内容宽度 1160px）。
  三轮共同的方法：**换样式层 + 少量装饰性 JS，结构与接口零改动**——
  `verify_ui.py` / `verify_quality_ui.py` 钉住的选择器全部保留（顺带补齐了
  verify 钉过但实际缺失的 `#btnKey`）。验证：容器实跑逐页截图过目；质量页
  「运行自检」真跑 64 用例 39/39 规则全绿。设计系统见 DESIGN.md。

- [x] **质量与验证搬上 Web 界面（2026-10-23）**。项目里最有说服力的资产是
  **验证记录**——39 条规则、黄金样本回归、107 站实跑准确率、18 条规则的回源核对
  台账。此前这些**全都躺在 `docs/` 与 `backend/tests/` 里，Web 界面一条都没暴露**：
  演示时只能说「我们很准」，用户只能选择信或不信。现在界面上有一页「质量与验证」，
  四样都能当场看。
  - **五个只读端点**（`/api/v1/quality/*`）：`rules` / `selftest` / `accuracy` /
    `ledger` / `overview`。全部只读、不碰库、不发外部请求，故不涉及租户归属。
  - **「运行自检」是真跑规则引擎**，不是读静态数字：构造 HTML 喂给每条规则，
    核对「该触发的触发了、该沉默的沉默了」。语料 **64 条用例覆盖 39/39 条规则**
    （每条规则至少一条「应触发」+ 一条「应沉默」——只测「该报的报了」的套件
    等于没测误报，而误报比漏报更难被用户发现：漏报用户会骂工具，误报用户会
    照着改，改坏了才发现）。
  - **规则目录从 `default_registry()` 实况导出**，不手抄清单。测试**双向**核对
    （目录多出的、注册表缺的都算失败）——只查正向的话，删规则时目录会留一条
    幽灵而界面照样显示。
  - **准确率给三档口径**（可判定 / 下限「存疑全算错」/ 上限「存疑全算对」），
    **最坏情况摆在明面上**。拿不到 `docs/accuracy_*.json` 时返回
    `available: false` 并说明原因，**不返回 0**——「没测过」和「测了是 0」是两回事。
  - **回源台账解析 `docs/verification-ledger.md` 的 Markdown 表格**，不另存 JSON：
    台账人工维护，解析它就没有第二份副本要同步。
  - ⚠️ **自检语料第一版就红了 3 条**（`noindex.present` / `link.noanchor` /
    `http.mixed_content`），查下来全是**期望值写错、规则本身是对的**：404 页要
    真的把 `status_code` 设成 404（规则靠它豁免）、空锚要**两个**才报（单个视为
    无害 UI 元素）、混合内容判定看 `final_url` 不看 `url`。这三条恰好证明自检
    不是走过场。
  - 界面遵守 DESIGN.md（零阴影、圆角 2/4px、状态「字符+颜色」双编码、数字等宽
    tabular-nums）。新脚本 `scripts/verify_quality_ui.py` 用 CDP 验页面**真的渲染
    出来了**（自检行数、规则条目、判据面板能否展开、有无错误盒）——不看图也能判。
  - 验证：754 测试全绿 / ruff 零告警 / mypy 零错误 / 新模块覆盖率
    `api/quality.py` 100%、`quality.py` 96% / 浏览器实测四页签全通。

- [x] **补 CLI 命令级用例（2026-10-22，决策③的后续活儿）**：`cli.py` 覆盖率
  28% → **41%**，全量 726 测试、80.2%。补的四条都在 `test_cli_persist.py`，
  走「真文件 + 真临时 sqlite + stdlib sqlite3 读回校验」这条路子（命令内部自起
  事件循环并缓存全局引擎，测试端再用 aiosqlite 查会撞「连接绑已关闭的 loop」，
  读文件反而是干净的外部视角）：`rank-import` 端到端（GSC 风格别名表头、坏日期
  报行号、重跑不涨行、位次留空落成 NULL 不是 0、`www.` 剥掉后推断出域名、站点
  不在库里时给下一步）、推不出域名时明确要 `--site`（用 `https://` 这种有协议没
  主机的畸形导出触发）、`rules` 按注册表实况逐条比对（防「已注册但列表里看不见」，
  cnh_eco 踩过的坑）、`main([...])` 派发（parser 默认值与命令函数对得上，
  缺必填 `--db` 由 argparse 以退出码 2 拦下）。同批查明一处粗糙：文件路径写错时
  是 traceback 不是一句人话——**下一轮已修**（`_read_input_file()` + 四条用例，
  `cli.py` 因此 38% → 41%），详见技术债那条与本轮 CHANGELOG「修复（CLI 入口的文件
  错误不再抛栈）」。
  验证：726 测试全绿 / ruff 零告警 / mypy 零错误 / 覆盖率 80.2%（门禁 78%）/
  `alembic upgrade head` + `check` 无漂移。

- [x] **产品决策落档（2026-10-22，产品负责人逐条确认）**：
  ① **M0「1000 URL ≤5 分钟」作废，默认 3 rps 不动**——选「保持礼貌 + 把指标改成
  实测事实」，理由是那个 5 分钟当初是拍的，而限速下界是真实约束（详见 M0 清单）。
  ② **SERP 代抓延后到盈利后**——未开始收入就引入固定付费源不合理，重启条件写在 P2 #15。
  ③ **下一笔活儿是补 CLI 命令级用例**，不是加功能；覆盖率门禁 78% **不下调**。
  ④ **API Key 保留为商业化底座**（不删、不重构），模式二与企业版都压在它上面。
  ⑤ **多租户/RBAC 按两份商业文档分步走**：先做账号-站点归属与数据隔离的最小闭环，
  角色表等第二个付费席位出现再建（详见 §4 M3 表）。
  ⑥ **GEO 规则包维持默认不加载**，先做方法论验证再谈进 `default_registry()`。
  ⑦ **README 统计口径以实测为准**，中英两份保持一致；中文版是默认，英文入口
  就叫 `English`。已落成真用例：`test_docs_stats.py` 把表数/表名对
  `Base.metadata.tables`、路径与操作数对 `app.openapi()`、中英两份的测试数与
  覆盖率徽标彼此对齐——宣传数字写两处就一定会分叉，这条不是洁癖。

- [x] **阶段 4（SERP 数据入口）2026-10-22**：补 Brief 竞品维度这个「静默死功
  能」。`serp_snapshots` 表从 M0 就躺在 schema 里，但**没有任何路径能往里写**
  ——`latest_for_keyword()` 恒空，Brief 的 Top10 共性/差异化机会一律走「竞品
  数据缺失」分支，而 caveat 文案还把原因推给「Search Console 未接」。现补
  `serpdata.py`：CLI `serp-import` + `POST/GET /sites/{id}/serp`，CSV 与 JSON
  两个入口共用同一套校验（`result_from_fields` / `capture_from_fields`），
  坏行逐行报行号。三条口径值得单独记：
  ① **位次必须是正整数名次**——小数平均排名属于排名时序，请走 `rank-import`；
  两者混进一张表，Top N 会被搜索量/竞品数之类的假位次污染。
  ② **`--site` 必填**——一次抓取里竞品域名占多数，按「出现最多的域名」自动
  匹配会把数据灌到竞品名下。
  ③ **没写抓取时间就按「今天 00:00 UTC」记一次快照，并当场打印出来**——
  静默补时刻等于让用户以为数据是当天抓的。
  仓库层 `SerpRepository.upsert` 以 (keyword, captured_at, url) 为键且对微秒不
  敏感，重复导入是更新不是插第二份；此前 `bulk_create` 的注释写着「幂等」
  而实现是无脑 INSERT——**那是谎报，不是省略**，已连带改掉。Brief 侧顺手修
  两处：market 参与取词（跨市场不再串数据）、「我方当前排名」改为真去
  `rank_history` 取最近一个有 position 的日期，取不到才明说不可用。
  验证：713 测试全绿 / ruff 零告警 / mypy 零错误 / `alembic upgrade head` +
  `alembic check` 与模型零漂移（13 表）。

- [x] **分支收敛：master 的阶段 1 / 2a / 2b / 3 合回 main（2026-10-22）**。
  此前两条分支各自向前跑：main 上有整改工单、排名数据入口、白标交付；
  master 上有工程地基（结构化日志 + CI mypy）、持久任务队列、定时复扫调度、
  Top 5 口径统一。谁都不是对方的超集，直接以 main 为准会丢掉约 2,400 行实现
  与 555 行测试。合并方向取 master→main（单向），合并后删除 master，
  此后只有 main 一条分支——与「项目只有一个主分支」的约定一致，但**先把
  两边的活儿都收进来再删**，而不是删了再说。冲突 5 处（README / CHANGELOG /
  api/schemas / api/routes / tests/test_api）按「两边的活儿都在，只重排归属」解决。

- [x] **测试隔离补洞（2026-10-22）**：① `test_web.py` 的 DNS 打桩改为**完全不
  发真查询**。开发机上代理的 fake-IP 模式（198.18.0.0/15 基准测试网段）会把
  `example.com` 也解析成保留网段地址，SSRF 守卫拒得对（400），但「测试过不过」
  就此取决于本机开没开代理——守卫自己的解析/拒绝用例在 `test_guard.py` 逐条
  控制解析结果，这里只需要「提交被接受」。② 「同域不重复建站」改为**翻页查**
  （`?limit=200&offset=N`）：列表默认只给 50 条，合并后的套件建站数早已过一页，
  只看第一页得到空列表，症状是「单跑绿、全量红」。③ fixpack / rankdata 的
  mypy 存量 10 处归零（`before` 真会返回 None 而签名写着 str、`Counter()` 缺
  参数化标注、`RENDERERS` 被 lambda 推断绑架）。教训同「阶段 1」那条：
  **类型检查扫的恰是测试的盲区**。

- [x] **阶段 3（Top 5 优先做）2026-10-21**：修「先做清单」三处口径分叉
  （网页自排 vs 报告排序 vs JSON/API 没有），统一由 scoring.top_actions
  服务端装配；API 补可执行改法三件套 + affected_pages。M0 验收项
  「Top 5 且每条有可执行改法」真站验证通过（antfu.me）。四道闸全绿：
  650 测试 / ruff 零告警 / mypy 零错误 / 真站实测。

- [x] **改造阶段 2b（定时扫描调度）2026-10-20**：托管定时复扫。
  `sites` 三列（迁移 0008）+ `scheduler.py`：到期站点自动入队，走
  2a 的持久队列。API `PUT/GET /sites/{id}/schedule`。调度语义四条各有
  测试：at-most-once（CAS 认领在前，宁漏勿双）、不叠任务（跳过入队
  但照常推进周期）、参数定格（快照）、队列满不认领（留 due 重试）。
  含接线测试（等 lifespan 的 scheduler_loop 自己触发）。托管最小
  间隔 1 小时。测试 tick 语义时用 monkeypatch 换全局 session factory
  而不是给 tick 加注入参数——加参数等于测一条生产不走的路。
  ⚠️ 顺手踩死一个老雷：lifespan 收尾无界 await 被取消的后台任务，
  取消撞上 SQLAlchemy 异步驱动的 greenlet/shield 交接区就会永久吊死
  （症状：测试套件随机挂起），收尾改有界等待（2s 到点就走），
  详见 CHANGELOG。

- [x] **改造阶段 2a（持久任务队列）2026-10-18**：scan_tasks 表（迁移 0007）+
  tasks.py 执行器。Web 任务从进程内存落库：重启不丢、多 worker 原子认领、
  孤儿任务启动恢复（attempts 限次重试）；同进程唤醒秒级开跑 + 跨进程
  慢轮询兜底；队列深度上限拒收。验收达成：杀进程任务不丢（有回归测试）、
  并发计数从行状态数出来（不存在忘减）。踩坑三枚：asyncio.Event 绑循环、
  嵌套 TestClient 双循环共享引擎、@dataclass 装饰器被插队接住。
  阶段 2b（定时扫描调度）待做。（**已于 2026-10-20 做完**，见上一条；这句留在
  这里是当时写下的原话，只补一句现状，不改历史。）

- [x] **改造阶段 1（工程地基）2026-10-18**：结构化日志 `log.py`（JSON/文本）+
  CI mypy 任务（存量 31 错误 → 0，配置钉在 `pyproject.toml [tool.mypy]`）+
  清理 routes/scan_service/cli 坏味道。顺手挖出两个真 bug：①关键词扩展端点
  正常路径 AttributeError（`kw_expand.expand` 把函数当模块调，测试只走到
  提前返回分支）；②Web 扫描站点级事实恒空（另起一只没探过任何东西的
  Crawler 喂 `_collect_site_facts`）。均已修 + 补回归测试，630 测试全绿。
  教训入库：**测试绿不代表路径通，类型检查扫的恰是测试的盲区**。

- [x] 需求规划书（REQUIREMENTS.md）
- [x] 执行计划（本文档）
- [x] M0 代码骨架：模型 / 提取 / 爬虫 / 规则引擎 / 评分 / 报告 / CLI
- [x] 22 条检查项（base 包）
- [x] Sitemap 发现与播种
- [x] 黄金样本回归测试（48 个用例，含渲染层）
- [x] 爬虫加固：自适应降速 / 连续失败熔断 / Crawl-delay
- [x] 误报治理第一轮（link.noanchor 28→0，soft404 分级，canonical 回访）
- [x] 报告展示：判定依据（verdict）置顶，不再被截断
- [x] 真实站点校准：107 站全集，严格准确率 **97.0%**（v7 全市场实跑；真误报 31 → 7）
- [x] 爬虫加固：sitemap 递归加墙钟 + 尝试次数上限（`9c4f344`）
- [x] 1000 URL 不断跑 / 断点续跑（1000 页 382s 实测）
- [x] **本机可运行环境固化**：`run.sh`（这台机器系统 Python 受 PEP 668 管控、
  venv 建不出带 pip 的环境，依赖装在 `.deps/`，此前每开一个新会话都要重新
  摸一遍才知道测试为什么跑不起来）
- [x] **Web 端可用**：深色界面，网址/页数/深度/市场/渲染 JS/robots 六个控件
  全部接后端；健康分环形图 + 6 维评分 + 严重度筛选 + 每条带「怎么改+示例」
- [x] **补上 `run_scan` 不回 `issues` 这个洞**：前端读 `rep.issues` /
  `rep.counts` 这两个字段压根不存在 → 旧页面只显示一个分数、下面列表永远
  空白，看着像「你网站没问题」。现已按 fingerprint 聚成行动项，
  `affected_pages` 记「一共多少页受影响」
- [x] **18 条规则回源核对全覆盖**（台账 `docs/verification-ledger.md`）：
  link.noanchor 34/34、meta.duplicate 25/25、title.duplicate 16/16 全量，
  误报各归零；另抽出我自己核对器栽过的 11 处
- [x] 端到端验证：python.org → 96.7 分 / 7 条问题，问题清单带回来了
- [x] 截图验证：**2026-10-04 已做**（Chrome 以 root 需 `--no-sandbox --disable-dev-shm-usage`）。
  `docs/shots/` 下 web_home / web_light / web_v3 三张，界面已按 `frontend-design-deslop`
  重做过一版。⚠️ 但**「截图在」≠「界面被验收」**——验收时的原话是「low 的一批」，
  按指示先搁下、不再投入
- [x] **2026-10-04 挖出并修掉 6 个真 bug（全都不是加功能，是补洞）**：
  1. **分数算了从没存进库** —— `crawl_jobs` 表压根没有 `health_score` /
     `score_breakdown` 两列，而 `_latest_score()` 去读 `job.score_breakdown`
     → 健康分**恒为 null**，前端一律按「一页都没抓到」渲染。**扫过的和没扫过的
     长得一模一样**：接口看着是通的，答案恒为空（`b56d1fb`）
  2. **趋势线没有数据源** —— 上一条修好后才解锁 `/sites/{id}/trend`；
     且刻意不把「抓取失败」那轮画进趋势线，那是**用一次失败冒充质量下滑**（`8bc7293`）
  3. **全站一个 patch put/delete 路由都没有** —— 用户没法把问题标成「已修」，
     产品就只是个只读报告，扫完没有闭环（`5abdca2`、`417d8e8`）
  4. **重扫无条件 INSERT，问题数只涨不跌** —— 用户标了「已修」，下次扫描原样
     再插一行，**「已修」按钮等于只能用一次**（`a93bd30`）
  5. **增量扫描谎报「已修好」** —— 304 页不重跑规则，但 `status_code` 仍是 200
     照样进 `ok_pages`，被同步逻辑当成「本轮扫过且没问题」。**这条是我自己
     埋的**，且撞上我在同一笔提交里写的「绝不谎报」（`ace84ae`）
  6. **历史重复行静默塌成僵尸** —— 只堵新的不去旧的，`by_key` 字典让同 key
     只留最后一条：**用户标「已修」落在僵尸上**，同一个问题在列表里出现两次。
     真站 9 组重复，被真脏数据打回来才发现（`20e000e`）
  - **共同的教训（已写进 6/5 的提交消息）**：单元测试全绿、`total` 也没翻倍，
    单看任何一项都发现不了 —— **只有拿真站、拿脏数据跑才炸出来。**
    测试环境干净时，绿灯不代表对。

- [x] **2026-10-18 整改工单（处方包 `fixpack.py`）**：报告回答「哪里不对」，
  工单回答「下周一改什么」——产品从体检工具跨到执行型 Agent 的第一步。
  处方分三档可信度（可照抄 / 机器起草待润色 / 只给配方）强制展示；
  判不了的转人工不硬凑；站点级问题逐页归因到「哪个页面改成什么」。
  四格式输出（md/json/csv/diff）+ 白标 `--brand`。CLI 与 API 同一份逻辑。
- [x] **2026-10-18 排名数据入口（`rankdata.py`）**：`rank-import` CLI +
  `POST/GET /rankings`，监测闭环从「只能看」变成真的能响。
- [x] **2026-10-22 Web 界面补四处「后端有、界面没接」的入口**：日级排名导入、
  SERP 快照导入、定时托管复扫、整改工单导出。为此新增两个**原始文本**端点
  （`POST /sites/{id}/rankings/import`、`POST /sites/{id}/serp/import`），
  解析口径仍只有 `rankdata` / `serpdata` 一份——**界面不解析任何字段**，
  前端写一套别名的收场一定是「CLI 导得进、网页导不进」。格式判定也收成
  一份（`serpdata.detect_format`）。每条导入卡配**回读表**，让用户自己查证。
  顺带钉了一条不变量用例：页面上 JS 用到的每条 `/api/v1/...` 路径必须能在
  `app.openapi()` 里找到（`app.routes` 看不到——API 挂在子应用上）。
- [x] 待办：单站 1000 URL 压进 5 分钟 —— **2026-10-22 决策（方案③）已落**：
  默认 3 rps 不动，「≤5 分钟」这条硬指标作废，改为引用实测
  「1000 页 ≈ 6.4 分钟（333s 墙钟下界 / 实测 382s）」。**加并发压不下去**——
  限速器按墙钟串行放行；要达标只能提高默认速率，代价是对第三方站更激进。
  取舍：礼貌优先，数字改成引用实测（见第 1.3 节 M0 清单与 CHANGELOG）。

## 8. 待办清单（按优先级）

### P0 — 阻塞 M0 验收

| # | 事项 | 说明 | 状态 | 预估 |
|---|---|---|---|---|
| 1 | **误报率下降** | 目标 ≥90%。**107 站全集：严格准确率 97.0%**（v7 全市场实跑，报告 723 条 / 可判定 530 / 存疑 193 / 属实 514 / 噪音 9 / 真误报 7；含噪音容忍 98.7%）。真误报 31 → 7。已修：link.noanchor 装饰性图标豁免（提取层 aria-hidden）、canonical 百分号编码归一、og.basic_missing 改 SITE 级、title.chinese_too_long 翻译视图+像素预算、title.too_short 功能性页豁免、title.missing JS 渲染守卫、hreflang x-default 兜底/视图参数/首页别名。⚠️ og 改 SITE 级后那 17 条因无单页 URL 归入「存疑」被排出分母，按最坏情况计入仍为 94.0% | ✅ 已完成 | — |
| 2 | **多站人工核对** | **107 站**（博客/电商/文档/政府/中文社区/大型企业站）自动回源核对。站点数从 23 扩到 107 是因为前两轮静默丢了 18 站——而那批恰恰是反爬/JS 渲染/畸形 sitemap 最容易暴露的，**删掉难样本的 96.9% 不能报** | ✅ 已完成 | — |
| 3 | **评分权重校准** | **有结论：权重不动。** 用 29 站 × 25 页重抓（601 页）验证——受影响面 r 的中位数降到 0.04~0.12，全站命中的只剩 0~11%，不再被 5 页样本下 0.2 整数倍的量化绑架。现权重 30/15/5 在这个粒度下表现合理，**原判断被数据证实，故不改**。之前「阻塞」的理由是样本量，样本量补上后原判断就成立了，不需要硬凑一个校准动作 | ✅ 已完成（结论：不改） | — |
| 4 | **报告文案审校** | 扫 37 条 rule 文案，判决性措辞 0 处。h1.multiple 的文案自相矛盾已随规则一并修掉 | ✅ 已完成 | — |
| 5 | **审计范围（追加）** | 实测 gymshark.com 抓 25 页有 24 页是 `us.checkout.gymshark.com`，124 条问题 119 条来自子域，主站被判 0.0 分。结账页带 noindex 是**正确配置**，却报成 CRITICAL「页面被屏蔽收录」——规则判得对、用户照做反而更糟。已新增 `same_site_scope()`：host 相同或仅差 www 才算本站（不能复用 `is_internal()`，它按可注册域判断，对内链权重传递才是对的）；分母也改为本站实抓页数 | ✅ 已完成 | — |

### P1 — M1 产品化前置

| # | 事项 | 说明 | 状态 |
|---|---|---|---|
| 5 | 数据库与持久化 | 当初 9 表，**现 13 表**（迁移 0001–0008）；`alembic check` 与模型零漂移（2026-10-22 合并后复跑 `upgrade head` + `check` 确认）；枚举降级为 VARCHAR+CHECK 使整层可脱离 PG 单测 | ✅ |
| 6 | FastAPI 服务层 | 7 端点（健康/站点CRUD/扫描触发/任务/问题/报告）；同步爬虫走线程池，异步 db 层不受阻塞；真 uvicorn 进程冒烟通过 | ✅ |
| 7 | 增量扫描 | **条件请求为主**（ETag/Last-Modified → 304 不重传正文），规则跳过为辅。跳过有三条硬约束：任一页面变化则全站重跑、失败页绝不跳过、读 site_facts 的规则必重跑 | ✅ |
| 8 | 代理 IP 轮换 | 403/429/连接被拒时换出口重试；重试按 URL 计数、上限=代理数（防活锁）；失败页不入报告 | ✅ |
| 9 | Google 规则包 | 5 条（lang / viewport / title 像素溢出 / hreflang 系列）。放弃 AMP、LCP、rel=prev/next —— 前两者已过期，第三者 Google 官方已声明不读 | ✅ |
| 10 | 百度规则包 | 5 条（robots.baiduspider / 中文标题 / 中文描述堆砌 / ICP / 移动页）+ cnh_eco 1 条（微信搜狗）。中英阈值分离，视图参数用白名单 | ✅ |

> ⚠️ **#7 的教训记在这里**：增量扫描第一版把 checkpoint 的 `visited` 回填进主循环，
> `if key in visited: continue` 把所有 URL 全跳过，**条件请求发出 0 次**。
> 实测现象极具迷惑性：第二轮 5s→1s、覆盖率 2.6%→80%，看着像「增量生效了」，
> 其实全是本地续跑短路，一个字节都没少传。**这比不 work 更坏——它看起来像成功了。**
> 判增量是否生效只认一行：`条件请求 N 次 / 304 N 次`，那是服务器行为，不受本地短路干扰。

### P2 — M2 智能层

| # | 事项 | 说明 |
|---|---|---|
| 11 | LLM 适配层 | litellm + instructor 封装，先做「报告 AI 总结」验证链路。⚠️ **实现与计划不同**：`llm.py` 是自建 httpx + OpenAI 兼容协议层（0 新增依赖，见 README「无付费数据源也能跑」的取舍），litellm/instructor 至今未引入。要么改计划认账现状，要么补依赖——现状能跑、也覆盖得起测试，暂按前者 |
| 12 | 关键词扩展与聚类 | jieba 分词 + pgvector 语义聚类。🟡 **实现与原计划不同**：聚类改成纯离线确定性实现（字符 n-gram + 相似度，0 embedding、0 pgvector），因为语义聚类要 embedding 就得要 API key，与「无 key 可用」这条铁律冲突。jieba 仍在，但只是**可选加速**——没装就退回字符切分（`expand.py` 的 `tokenize()`） |
| 13 | 内容 Brief 生成 | 目标词、意图、Top10 共性、差异化机会。✅ 四要素都在，但 Top10 共性**取决于有没有 SERP 数据**：2026-10-22 补上 `serp-import` / `POST /serp` 之前这条路是死的（表在、没有入口），现在导一次快照就能出竞品共性，没导就明说缺失。我方位次取自 `rank_history`（见 `own_rank`） |
| 14 | GEO / AI 搜索可引用性 | 差异化重点，需先做方法论验证。🟡 规则包 `geo`（4 条）已就位，但默认不加载、不进基线，方法论验证仍未做。**2026-10-22 决策：维持现状**——继续经 `--market geo` 点名启用，验证做完前不进 `default_registry()` |
| 15 | SERP 自动抓取 | ⬜ **2026-10-22 明确延后（盈利前不接付费源）**。阶段 4 交付的是**入口**（用户/跟踪器/SERP API 导出 → 落库），已经够用；代抓要接 DataForSEO / SerpAPI 之类付费第三方，在没有收入之前引入固定成本不合理。重启条件：有付费客户明确要求竞品全貌，或 ¥99/¥399 档出现「因为没竞品数据而流失」的证据 |

## 9. 已知技术债

- **孤岛页检测依赖覆盖率**：`hit_page_limit` 时一律不下结论，即使已抓 1000 页。这是**设计取舍不是 bug**——「我没发现指向它的内链」只有在确信「大部分页面都看到了」时才成立。建议 M1 加「分批跑完整个站点」的扫描模式。
- ~~**`baidu` 包本地移植了 google 的像素宽度表**~~ **已清偿（2026-10-12）**：宽度表上提到中立模块 `audit/rules/_serp_px.py`（不 import 任何规则包，不会成环），两包改为引用同一份，「改 google 必须同步 baidu」的人工约定删除。指标值不变（test_fp_baidu_2026 的像素断言钉着）。
- **GEO 规则包需显式开启**：`default_registry()` 不加载它，以免证据强度较弱的新规则污染 base 的 97.0% 准确率基线。✅ 2026-10-22 决策：维持现状直到方法论验证做完（`--market geo` 点名启用；`cli.py` 的规则列表处已打印这条差异）。
- **薄接线层没测（2026-10-22 开始收）**：覆盖率 80.0%、门禁 78%，余量 2.0 个点。
  `cli.py` 原 28% → **41%**：`rank-import`（别名表头 + 坏行报号 + 幂等重跑 +
  位次留空落成 NULL 而不是 0 + 推断出的域名 + 站点缺失时的下一步提示）、
  `rules`（按注册表实况逐条比对，防「已注册但看不见」）、`main([...])` 派发
  （parser 默认值与命令函数对得上）都补了命令级用例，范本是
  `test_cli_persist.py` 里的 `serp-import` 那条（真文件 + 真临时库）。
  **仍开着的**：`api/routes.py` 37%——30 个路径里真正被测的仍只有导入、Brief、
  fixpack 那几条。2026-10-22 给界面补的两个原始文本端点是有用例的（9 条），
  但比例被同批新增的行数摊平，**没涨不代表白测**；`cmd_scan` 只有 API/Web 侧的
  作业级用例，CLI 侧「参数 → 落库 → 报告落盘」整段仍靠 `guard_smoke.sh` 的真容器冒烟，本机跑不到。
  ⚠️ 补这批用例时发现一处粗糙：`rank-import` / `serp-import` 的文件参数给个
  不存在的路径，`Path.read_text()` 直接抛 `FileNotFoundError`，用户看到 traceback
  而不是一句人话。**2026-10-22 已修**（用户确认后进行）：两处入口改用共用的
  `_read_input_file()`，「文件不存在 / 那是个目录 / 不像文本文件 / 其他 OSError」
  四类各打一句 stderr 并返回退出码 1。踩到的跨平台细节：**读目录在 Windows 上抛
  `PermissionError(13)`、POSIX 上才是 `IsADirectoryError(EISDIR)`**，所以先自己
  `is_dir()` 判、再兜异常，否则同一句提示两个系统长得不一样（用例在 Linux/CI 上
  会绿、Windows 上红，反过来也一样）。补覆盖**不要靠下调门禁续命**。
  ℹ️ `cli.py` 41% 里剩的两处未覆盖（`_read_input_file()` 的 `IsADirectoryError`
  分支与兜底 `OSError` 分支）是**测不到的兜底**，不是漏测：前者只在「`is_dir()`
  判完之后目录才出现」这个竞态窗口里走（本机测的是常规输入），后者要靠
  `chmod 000` 才有意义，而 Windows 上不限制读权限——为它们专门进 CI-only 用例
  会让本机与 CI 的覆盖率口径分叉，不值当。代码处已写注释，别当死代码删。
- **Windows 上 `alembic` 读不了自家 ini**：`backend/migrations/alembic.ini`
  里有中文注释，alembic 用 `encoding="locale"` 读它，中文环境下直接
  `UnicodeDecodeError: 'gbk'`。CI 是 Linux 所以从未暴露。
  ⚠️ **2026-10-22 实测：环境变量救不了**——`PYTHONUTF8=1` 与 `-X utf8` 都试了，
  `locale.getpreferredencoding(False)` 在 UTF-8 模式下确实返回 utf-8，
  但 configparser 把 `encoding="locale"` 折成 `None` 交给 `open()`，
  `open()` 走的是启动期缓存的 ANSI 代码页（cp936），照样炸。别再猜「加 BOM」，
  那条也没用（读的时候编码已经定死了）。
  两条能用的绕法：① 拷一份 ASCII ini 再 `-c` 指过去——会在仓库里留垃圾，
  用完必须删；② **根本不读 ini**：`Config()` +
  `set_main_option("script_location", os.path.abspath("migrations"))`，
  直接 `command.upgrade(cfg, "head")` + `command.check(cfg)`。②今天实测通过
  （末行 `No new upgrade operations detected.`），不落任何临时文件。
  根治：ini 里的注释改成 ASCII（中文说明挪进 `env.py` 或 `DEPLOY.md`），
  或在 `scripts/` 固化 ② 这个无 ini 的检查入口——**别改成「读不出来就算了」**，
  那等于关掉这道闸。
- **测试跑法有非确定性（2026-10-22 复查发现；2026-10-23 部分修复，根治未竟）**：
  同一份代码全量连跑，覆盖率在 **79.99%–80.03%** 之间漂；把 `RuntimeWarning`
  升级成错误（`-W error::RuntimeWarning`）能放大成 `test_multitenant.py` 两条
  用例 **ERROR**，另一次直接**挂住不退**（8 分钟无 CPU 活动，只能杀进程）。
  默认跑法多次全绿，所以四道闸照旧能过——**但别把它读成「测试很稳」**。
  - **2026-10-23 查明的真根因**（此前一直误判成「多模块共用一个库」）：
    `test_multitenant.py` 的 `tenant_client` fixture 用**裸 `sqlite3.connect`**
    往库里塞钥匙。那与应用引擎的 aiosqlite 连接是**两个连接**，在同一个库
    文件上争写锁；而 TestClient 的 lifespan 跑在**另一个线程**的 event loop
    里（starlette 用 anyio 的 `BlockingPortal`），于是「应用侧持锁」与
    「测试侧要写」是**真并发**——撞上就报
    `sqlite3.OperationalError: database is locked`。
    ⚠️ 顺带查明一件反直觉的事：**建表事务一旦提交，锁立刻释放**——所以
    「create_all 提交后裸写入仍失败」这个假设是错的，此前一直在错的假设上
    找解法。
  - **✅ 已修**：建钥匙改走应用自己的 `POST /api/v1/keys`（用管理令牌 +
    `x-owner` 头指定归属）——全程**只有一个连接**在写这个库，锁竞争从根上
    不存在。顺带的好处：这条路**真的走了一遍生产用的签发流程**（owner 归属、
    哈希落库、明文只返回一次），而原先手工 INSERT 出来的钥匙**绕过了生产
    代码路径**——那才是更该担心的隐患。配套补了**站点数据清理**（每个用例
    前清表）与**只读模式**（`mode=ro`）的两处只读查询。
  - ⚠️ **不要用 busy_timeout / retry**：实测给两侧连接都加 `timeout=5` 之后，
    失败轮次耗时从 45s 涨到 114s（**真的在等锁等到超时**），而问题一个没少。
    已撤回。本条原先就警告过「别用 retry 掩盖」。
  - ❌ **试过并回退的两个方案**（记录在此，免得下一个人再走一遍）：
    ① `backend/tests/conftest.py`（模块级 autouse fixture，每个测试模块开始前
    把全局引擎重建到该模块自己的库文件）——**实测比原状态更差**：第 1 轮就
    出现 5 个 error + 1 个 failed（原状态是 2 个 error），失败点从
    `test_multitenant` 扩散到别的模块。已整份删除。
    ② 把临时库统一到「一个父目录 + 一个文件」——**更糟**：上一轮跑测试的
    残留（`site1.test` 之类）会活到下一轮，下一轮的用例建同名域名就撞 409，
    一次跑挂 64 条。已整份删除。
    ⚠️ **教训**：引入「重建全局单例」这种机制会改变整个套件的状态传递方式，
    影响面远大于它要解决的问题。遇到「测试互相影响」时，**先找那个具体的
    并发点**（本次是 fixture 里的两行代码顺序 + 一个裸连接），别急着上
    结构性改造。
  - ❌ **仍未根治**：套件**大多数轮次全绿**，但偶发仍有 1–2 个 error 或
    「跑完用例后挂住不退」。⚠️ **这是既有现象，不是本轮引入的**——用原始
    代码（`git show HEAD:` 复原到独立目录）连跑 10 轮，同样在第 3 轮出现
    2 个 error，症状一模一样。剩下的根因指向 **lifespan 收尾**：TestClient
    退出时 `dispose_engine()` 把全局引擎置空并 dispose 连接池，而收尾是
    **有界等待 2s**（见 `main.py` 里那段「取消落在 greenlet 交接区就永久
    吊死」的注释）——2s 到点就走 → 任务被 cancel → **连接池状态残缺**；
    下一个 TestClient 建新引擎时，旧连接的残骸还在同一个库文件上争锁。
    ⚠️ 彻底修要动 lifespan 收尾的取消语义（取消时**不** dispose，或改成
    显式的连接池重建），那是**结构性改动**、牵涉应用生命周期——**不该在别的
    活儿里顺手做**。本轮把问题定位到这一层并如实记下。
    ⚠️ 也**别用 retry 糊**：那等于把「连接池残缺」藏得更深。

---

## 10. 2026-10-25 全库复查发现（克隆复检，全部未修，按类归档）

> 方法：对爬虫/规则引擎、API/Web/任务层、数据层、部署工程四块做全文细读，
> 高严重度条目已逐条回源核对代码原文（引出行号均为当前 main `04d22d5`）。
> 本节只记**新发现**，与 §9 已知技术债不重复。标 ⚠️ 的是存疑或取舍空间大的。

### A. 正确性 bug（建议下一轮直接修，均有实测证据）

0. **🔴【2026-10-25 容器实测复现 + 修法已验证】文件型 SQLite 也被套上
   StaticPool，默认 Docker 部署下 Web 扫描 100% 失败**
   —— `session.py:97-105` 的条件是 `target.startswith("sqlite")`：注释只
   为**内存库**justify StaticPool（跨连接共享同一份内存数据），但条件把
   **文件库也匹配进去了** → 整个进程所有会话共享唯一一条 DBAPI 连接。
   时序（容器实测）：worker 会话的长事务里 `create_crawl_job`/`upsert_page`
   已 flush 未提交 → 爬取进行中，**轮询 `GET /jobs/{id}` 的会话一关闭，
   连接池 reset 就把这条共享连接 ROLLBACK**（StaticPool 没有「归还」概念，
   reset 直接打在正被别人用的连接上）→ worker 随后的 `INSERT INTO issues`
   引用的 crawl_jobs/pages 行已蒸发 → `FOREIGN KEY constraint failed` →
   整场扫描随事务回滚全部丢失，scan_tasks 里只剩一条 failed。最小复现
   脚本已验证（独立会话 SELECT 后正常关闭，再插 issues 即炸）。758 个
   测试全绿抓不到它：测试全用内存库（StaticPool 恰好是对的），且
   TestClient 的时序里没有「爬取窗口内插入轮询会话」。**为什么之前没人
  撞上**：本机跑 Web 时同样会炸（文件库默认路径 `./seoclaw.db`），但
   README 的冒烟路径是 CLI `seoclaw scan`（不开 Web 不轮询）；guard_smoke
   只打同步闸门不跑完整扫描——**「测试绿 ≠ 部署能跑」的又一实锤**。
   修法（已在 WSL 容器实测通过）：StaticPool 只给内存 URL
   （`//:memory:`、`mode=memory`、空路径），文件库走默认池；修后同一
   quick-scan 全链路 done（health 55.0 / 4 条问题 / 落库完整）。⚠️ 修完
   还应连带处理 §9 的「巨型事务」问题（文件库多连接后，长事务持写锁
   与并发写的 `database is locked` 风险才真正暴露，建议一并开 WAL +
   busy_timeout 并分段提交）。
1. **增量模式的 checkpoint 落盘偏移错位，第二轮起快照永远写不进 pages.jsonl**
   —— `crawler.py:749` `_load_checkpoint` 无条件 `self._pages_persisted = len(pages)`
   （旧页数 N），而 `crawler.py:390-398` 增量模式**不预填旧页**、本轮 `pages`
   从 0 开始；`_save_checkpoint` 的 `pending = pages[self._pages_persisted:]`
   （`crawler.py:840`）在本轮页数 ≤N 时恒为空切片。后果：变更页的新
   etag/last_modified 永不落盘，后续轮次只能整页重传——**增量静默失效**，
   且文件里新旧条目混杂。`test_incremental.py:180` 只数条件请求、不查落盘，
   所以全绿。修法：增量模式开跑时 `_pages_persisted = 0` 并重写（truncate）
   pages.jsonl——本轮是完整快照，不是续传。
2. **CLI `scan --db` 落库路径同时复现两个已修过的历史 bug**
   —— `persist.py:137` 用 `save_issues`，而 `repository.py:1633` 自己警告
   「只用于首次落库，重复扫描请走 sync_issues_for_scan——每扫一次多一整套
   重复行」（API 路径已改，`scan_service.py:240`；CLI 没改）；且
   `persist.py:152-156` 的 `finish_job` 不传 health_score/score_breakdown
   （`cli.py:290` 已算出但丢弃）→ 复现 2026-10-04 修过的「分数恒 null」
   bug（`b56d1fb`）——CLI 扫的站在 Web 界面上一律渲染成「一页都没抓到」。
   修法：`persist_scan` 改调 `sync_issues_for_scan`（scoped_urls 参照
   `scan_service.py:254` 排除 304 页）+ 透传两个分数参数。一次改动消掉两条。
3. **MCP `seo_audit_url` 从不 commit，扫描结果随会话关闭回滚**
   —— `mcp_server.py:96-109` `async with session` 内 `run_scan` 后直接
   return，无 commit；`tasks.py:117-119` 的注释明说「run_scan 自己不提交，
   这里必须自己 commit」。返回给模型的报告是对的（更具迷惑性），但
   site/job/pages/issues 全部蒸发，`seo_list_sites` 看不到刚扫的站。
4. **inbound_links 以原始 href 为 key，规则侧按 p.url 查表，系统性低估入链**
   —— `engine.py:210-212` `inbound[link.href] += 1`（key 是 urljoin 出的
   原始绝对 URL，含 www/协议/utm 变体），规则侧用 `ctx.inbound_links.get(p.url, 0)`
   查询。www 与裸域混用、链接带 utm 时入链被算到**永远查不到的 key** 上 →
   非 0 入链被读成 0 → `orphan.page`（HIGH）与 soft404 的
   `likely_true_soft404` 误报——正是本项目最不能接受的错误类型。修法：
   两侧统一用 `normalize_url()` 作 key。
5. **ctx.coverage 把失败页算进分子，覆盖率口径与 CLI 矛盾**
   —— `engine.py:223` `crawled=len(pages)` 把 429/403/timeout 页也计为
   「已覆盖」，而 `cli.py:234` 只数 `status_code == 200 and not p.error`
   （注释自己写着「算进分子就成了『抓到了』」）。100 页发现、60 页失败时
   coverage=100%，站点级规则照常开口——恰是「覆盖率不足必须沉默」铁律的
   反面。site_facts 里现成有 `pages_ok`，build_context 不读。修法：分子改用
   成功页数。
6. **队列路径下失败的扫描在 crawl_jobs 不留记录，「必须落 failed」的注释意图落空**
   —— `scan_service.py:309-311` 异常分支 `finish_job(FAILED)` 挂在**未提交的**
   session 上；tasks 路径里 run_scan 抛异常后该 session 直接退出回滚，job 行
   连 RUNNING 都没提交过（失败痕迹只剩 scan_tasks.error）。API 同步路径因
   `deps.py:22` 的 `finally: commit` 反而能落 FAILED——**同一失败两种历史**。
   修法：run_scan 的 FAILED 分支用独立事务即时提交。
7. **SERP 导入把所有词一律 `is_tracked=True`，口径与列定义相反**
   —— `serpdata.py:505-508` 新建关键词一律 `is_tracked=True`；而
   `models.py:602` 定义「False 的词 = 内容缺口」、`persist.py:181-185` 为此
   做了保守的 title-token 判定。导入的竞品词全被当「已在竞争」，缺口分析失真。
   修法：新建默认 `is_tracked=False`。
8. **`rank_history.recent` 用 `days * 1000` 魔数截断，超 1000 URL 的站静默丢行**
   —— `repository.py:1362` `.limit(days * 1000)` 按「天×1000 行」而非按日期
   过滤；30 天窗口 1200 URL 的站最旧数据无提示丢弃，**跌幅告警的输入不完整
   且无日志**，违反「数据诚实」底线。`ix_rank_site_date` 索引现成，改
   `WHERE date >= :cutoff` 即可。顺带：`rankdata.py:220-229` `ingest_rows`
   把解析出的 keyword 字段整个丢掉（`rank_history.keyword_id` 列与
   `ix_rank_site_keyword_date` 索引全闲置），且 upsert_day 每行 2 次往返、
   万行导入 2 万查询。
9. **前端「状态」筛选器静默失效；「扫描历史」健康分列恒为 "—"**
   —— `index.html:999-1002` 发送 `status` 查询参数，但 `routes.py:324-340`
   的 list_issues 签名只有 severity/code/limit/offset，FastAPI 静默丢弃
   （仓储层其实支持，`repository.py:945`）；用户选「已修复」仍看到全部——
   对靠状态闭环的产品是功能性误导。`JobOut` 无 `health_score` 字段
   （`schemas.py:43-51`），前端 `index.html:1128` 永远走 null 分支。
10. **`max_html_bytes` 在完整下载之后才检查，形同虚设**
    —— `crawler.py:627+656` 非流式 `client.get` 整个响应体先进内存，然后才
    `len(resp.content) > max_html_bytes`。内链指向的 500MB PDF 会先被完整
    下载驻留。修法：`client.stream` + 分块累计、超限即断。同类：`crawler.py:574`
    HEAD 被拒后 GET 回退会把整张 og:image 拉进内存只为读状态码。

### B. 安全（单机 127.0.0.1 形态风险可控；公网/SaaS 化前的硬门槛）

11. **SSRF 守卫只接在 web quick-scan 一条路上，API 扫描链路完全无守卫**
    —— `routes.py:195-231` POST /scan 从 `body.url` 直接进 `run_scan`，全文件
    无 `resolve_and_check`/`check_denied`；`PUT /schedule` 的 url 同样不校验
    （`routes.py:275`，定时复扫会带着任意 URL 长期去扫）；`SiteCreate.domain`
    无格式校验（`schemas.py:15`，可填 `169.254.169.254`）。最糟的一条：
    `verification.py:102-103` 站点归属验证 `check_meta` 用
    `follow_redirects=True` 且**提交时零校验**——外站 302 到
    `http://169.254.169.254/` 会照跟。修法：守卫收口到 `run_scan` 入口一处，
    httpx 侧挂重定向逐跳复检。
12. **`GET /api/v1/web/jobs/{id}` 无归属校验，SaaS 模式跨租户读报告**
    —— `web/__init__.py:181-207` 只查 ScanTaskRepository，不校验
    owner/站点归属，`report=row.result` 含域名与问题清单；任一持 key 租户可
    枚举 job_id。同批：quick-scan 建站 owner 落默认 `"local"`
    （`web/__init__.py:163`，对比 `routes.py:116` 特意写了 owner），租户自己
    看不到自己提交的站，且该路径不过 `quota.enforce`。
13. **处方包 CSV 导出无公式注入防护** —— `fixpack.py:631-632` before/after
    直接来自被抓站点可控内容（title/h1/meta/alt），首字符 `= + - @` 或 TAB
    时 Excel 打开即执行公式（CSV injection/DDE 经典路径）。修法：渲染前对
    危险首字符加 `'` 前缀，几行 sanitize。
14. **渲染 UA 用占位域名，违反自己立的规矩** —— `render.py:232`
    `+https://example.com/bot`，而 `crawler.py:36-43` 的注释明确批判过占位
    域名并把 `DEFAULT_UA` 改成真实联系方式。渲染流量恰是最敏感的那部分。
    修法：复用 `crawler.DEFAULT_UA`。
15. ⚠️ **无前置代理的直连部署下 XFF 最右值可伪造、限流可绕过**
    —— `guard.py:228-232` 取 `parts[-1]`；默认自部署形态没有可信反代时整个
    XFF 都是攻击者构造的。修法：加「前面有可信代理」开关，默认用
    `request.client.host`。
16. **guard 的 DNS 解析跑在事件循环上且 timeout 参数是死的**
    —— `guard.py:94` 签名收 `timeout` 从不使用；`web/__init__.py:131` 在
    `async def` 里直接调同步 `socket.getaddrinfo`——一个慢解析可卡住整个
    服务（恰是项目注释反复强调要避免的故障模式）。修法：
    `loop.getaddrinfo` 或 `to_thread` + `wait_for`。

### C. 部署配置（死配置 / 被架空——不影响本机跑，上 Render 前必须修）

17. **render.yaml 部署用不上它自己开的 PostgreSQL，数据必丢**
    —— `Dockerfile:32` 把 `SEO_CLAW_DATABASE_URL=sqlite+aiosqlite:////srv/data/...`
    烤进镜像，而 `session.py:51-56` 的优先级里它排在 `DATABASE_URL` 之前；
    `render.yaml:36-39` 只注入后者。Render 容器里 SQLite 永远赢 → 写临时
    文件系统，免费实例每周重启即全量丢数据，`render.yaml:9-10` 自己反复
    警告的「必须用 PG」恰好没生效。docker-compose 没踩坑是因为
    `docker-compose.yml:18` 显式重设了同名变量。修法：render.yaml 改注入
    `SEO_CLAW_DATABASE_URL`，或 Dockerfile 不烤 URL。
18. **`SEO_CLAW_RPS` 是死配置** —— `docker-compose.yml:21` 与 `render.yaml:43-44`
    都在设，`backend/seoclaw` 全库无一处读它（实际限速是
    `scan_service.py:191` / `crawler.py:52` 的硬编码默认值）。render 想压到
    2 rps 的意图被静默忽略；compose 设 3 恰好撞上默认值所以看不出来。
    修法：要么接进配置，要么从两份部署文件删掉。
19. **render.yaml 公网服务默认零鉴权** —— `SEO_CLAW_AUTH` 默认 `"off"`
    （`auth.py:42-43`，docstring 明说前提是单机自部署），envVars 没设
    token/鉴权开关——拿到 URL 的任何人都能驱使扫描器对外发请求。
20. **依赖三份清单并行，已事实漂移** —— `backend/requirements.txt:26` 写裸
    `sqlalchemy==2.1.1`（根 `requirements.txt:10` 写 `SQLAlchemy[asyncio]`
    并用事故注释强调缺 greenlet 会 ImportError）；`backend/requirements.txt`
    全文无 uvicorn（照它装=有 fastapi 没 uvicorn 命令）；CI 装 extras、镜像
    装钉版 requirements——**CI 绿不等于镜像里的版本组合被测过**。建议收敛
    单一来源（pyproject），requirements 由它生成。
21. **仓库无 `.gitattributes`，Windows 检出的 `run.sh` / `guard_smoke.sh` 是
    CRLF** —— WSL 里直接 `./tools/guard_smoke.sh` 报 `$'\r'`。修法：加
    `.gitattributes`（`*.sh text eol=lf`）+ 重规范化。
22. **Dockerfile 无 pip/apt 换源参数位** —— `Dockerfile:9-11,18-19` 直连
    deb.debian.org 与 pypi.org，全文件无 ARG；国内构建慢/抽风时只能改
    Dockerfile 本身。建议 `ARG PIP_INDEX_URL` / apt 源参数化。
23. **compose 无资源限制、无 init** —— CMD 的 uvicorn 当 PID 1
    （`Dockerfile:41`），`docker-compose.yml` 全文无 mem_limit/init；
    `render.yaml:24-25` 自己警告过 OOM。

### D. 性能与资源（不改变行为，纯省）

24. **每页 HTML 被 lxml 重复解析 2~3 遍** —— `extract.py:246` 一遍、
    `_derive` 里 `extract.py:718` 混合内容检测又一遍、trafilatura 失败兜底
    第三遍（615）；`_looks_client_render_failure` 与 `_full_visible_text` 是
    完全相同的两步正则各跑一遍（183/595）。大站扫描纯翻倍 CPU。修法：doc
    传入 `_derive`，可见文本算一次共用。
25. **BFS 用 `frontier.pop(0)`，O(n²)** —— `crawler.py:420`，frontier 可到
    十万级条目，每次 pop(0) 全量 memmove。一行换 `collections.deque`。
26. **sitemap urlset 去重对 list 做成员检查，O(n²)** —— `sitemap.py:251`
    `if loc not in result.urls`，MAX_URLS=20000 上限内最坏约 2×10⁸ 次比较。
    伴随 set 即可。
27. **自适应降速只降不升，且被外部目标连带** —— `crawler.py:148` 的
    `per_domain_rps / divisor` 是全库唯一写点，无任何恢复代码（docstring
    声称「后续再逐步恢复」）；`_probe_targets`（579-580）探测外站 CDN 失败
    会把**主站**速率一起降档。少数几个 403 即可把整轮钉死在 0.05 rps 下限
    （20s/请求）。同病：`Crawl-delay` 是死功能（`crawl_delay()` 全库零调用，
    `crawler.py:186`），且 `_parse_crawl_delay`（229-232）取 `min`（最快档）
    与注释「保守值」相反——礼貌意义上的保守应是 `max`。
28. **整场扫描压在一个巨型事务里** —— `scan_service.py:206-292` 在
    `create_crawl_job`（flush 即拿 SQLite RESERVED 写锁）后跨分钟级
    `to_thread` 持有同一 session；`session.py:9-12` 自己的设计注释写着「把
    一次扫描切成上百个事务」。期间任何写（quick-scan 入队、issue 状态更新、
    `auth.py:109` 每请求的 last_used_at 更新）都会 database is locked；
    MAX_CONCURRENT=2 的两个扫描在 SQLite 上必然互杀。修法：分段提交 +
    SQLite 开 WAL + busy_timeout。⚠️ 与 §9 lifespan 技术债同源（SQLite 锁
    语义），修时一并考虑。
29. **`sync_for_scan` 每轮全量加载该站全部 Issue ORM 对象并逐条 flush**
    —— `repository.py:829-837` 无投影无 limit（同文件 971 行自认「大站问题
    行可达十万级」），循环内逐条 `create` 各自 flush。修法：投影只取
    `(fingerprint, url, id, status)`，新行攒批。同批小项：
    `group_by_fingerprint` 每组一条 sample_urls 查询（994-1003，limit 50
    封顶，量级可控）。
30. **`_probe_targets` / robots / sitemap 请求绕过代理池与限速器**
    —— `crawler.py:205` RobotsCache 与 `sitemap.py:76` SitemapFinder 各自
    `httpx.Client(...)` 直连：配置代理池时这两个请求暴露真实 IP，与「换 IP
    重试」设计矛盾；SitemapFinder 子文件循环最多 200 次请求完全不限速，
    违背自己第一位的「单域 3 rps」。修法：把 Crawler 的 client/limiter
    传给二者复用（顺带消掉 robots.txt 每轮被抓两遍）。

### E. 数据模型与接口一致性（潜伏雷 / 死字段）

31. **三个「承诺回填」的字段从未被写入** —— `models.py:89`
    `LinkRef.target_status`（注释「抓取阶段回填」，全库唯一出现处是声明）；
    `Page.fetched_at` 从不赋值，`persist.py:77` 用 `datetime.now()` 兜底——
    落库的是**入库时间冒充抓取时间**；`Issue.impact` 列全链路无写入方
    （`api/summary.py:43` 恒空串）。要么实现要么删列。
32. **`occurrences`「每次扫描重算」的承诺未兑现** —— `models.py:558` 注释
    如此，唯一 writer `refresh_occurrences`（`repository.py:1047`）无生产
    调用；读侧 `routes.py:162/353`、`summary.py:41` 用 `or 1` 掩盖——
    「批量修复价值」排序依据实际恒为 1。修法：sync_for_scan 收尾按指纹
    GROUP BY 回填一条 UPDATE。
33. **`sync_for_scan` 刷新已认领行时不更新 title/description/fix_hint**
    —— `repository.py:888-891` 只写 job_id/page_id/severity/last_seen_at，
    规则文案升级后旧行永远展示旧标题。
34. **0008 迁移用 `sa.JSON()`，模型是 JSONB variant** ——
    `0008_site_scan_schedule.py:46` vs `models.py:57`；PG 上迁移建 JSON、
    create_all 建 JSONB，违反 0001:22-24「迁移必须和应用模型产出同样的库
    结构」的自定规矩（SQLite 测试暴露不了，`alembic check` 在 PG 上会报漂移）。
35. **AI 总结的输入喂了错语义的字段** —— `routes.py:664-670`
    `_Shim.pages_discovered = page.total`，而 `page` 是 **issues** 分页——把
    问题总数当「发现页数」写进 LLM prompt，数字前提被污染（pages_crawled
    的 `or page.total` 兜底同病）。修法：从 pages 计数或 job 行取。
36. ⚠️ **若干低频小项**：`quota.py:49` 月末 23:59:59–24:00 的计量事件落在
    窗口外；`routes.py:109-113` 并发建同名站 IntegrityError→500 而非 409；
    `routes.py:803,949-957` 结构化导入的 errors 未过 `_bounded`（最多 5000
    条逐行返回，raw 路径都过了）；`persist.py:129` 用 `finish(RUNNING)` 登记
    开跑会提前写 finished_at（已有专门的 `start()`）；`cli.py:417` 0 页成功
    仍退出码 0，脚本化无法区分全军覆没；`expand.py:195-204` PMI 把「本页
    seed 命中数」当概率用（量纲错误）且 O(页数²×候选)；`keywords/cluster.py:157`
    `embed_fn` docstring 说「传入即语义聚类」、实现是 raise NotImplementedError；
    `index.html:713-739` 体检轮询循环无导航取消、多次提交叠加孤儿循环；
    `index.html:1951-1964`「开始体检」走同步 /scan 分钟级阻塞（后端队列早就有，
    前端没接）；`tasks.py:40,165-166` MAX_CONCURRENT=2 但 worker 串行 await，
    单进程内恒 1 并发；`sitemap.py:48-54` 不支持 sitemap.xml.gz（Google 官方
    支持，.gz 子树静默丢失）；`util.py:90-93` 二级后缀表只有 7 项（缺
    com.au/com.hk/co.kr 等），`example.com.au` 与 `other.com.au` 判为同站
    → 跨站抓取；`scoring.py:37-52` performance 是雷达图死轴（viewport/mobile
    全落 content）、`scoring.py:137-141` site/page 两个 ratio 分支数学等价
    （`max(1, len(urls))` 恒空操作，注释宣称的区别不存在）；`render.py:174-205`
    close() 不清 `_shared_browser/_shared_playwright` 类属性，后续实例复用
    已关浏览器的死句柄（⚠️ sync Playwright 跨线程复用问题存疑，表现可能是
    `_render` 吞异常后渲染静默全失效）；`alerts.py:81-91` 跌幅只看首尾两点
    （⚠️ 可能是有意取舍，至少该在 evidence 里标注口径）；`repository.py:1534`
    ContentBrief 查重不带 site_id（当前无生产调用，潜伏跨站覆盖）；
    `.gitignore:84-85` 想忽略的 `tools/run_fp_*.sh` 等已被跟踪（规则失效）；
    `Dockerfile:19` `pip install fastapi uvicorn` 与钉版 requirements 重复、
    `Dockerfile:21` COPY 的 pyproject.toml 从不使用；`tools/guard_smoke.sh:141`
    KEEP 提示里的容器名过期（实际叫 seoclaw_guard_smoke）。

### F. 复查中确认**不用改**的（防止下一轮误报）

- `--market action="append", default=["base"]` 使 `--market google` 实际为
  `['base', 'google']`——这是 README 明文写的叠加语义（「始终包含 base」），
  不是 bug；残余小疵仅 `cli.py:164` 的 `or [Market.BASE]` 兜底成为死代码。
- Dockerfile 非 root、curl 健康检查、依赖层缓存顺序、`/srv/data` 卷与 DB
  路径四方一致、alembic `script_location=%(here)s` 位置无关、无任何
  git+URL 依赖、全部依赖有 manylinux wheel（python:3.12-slim 无 gcc 可装）。
- 迁移链 0001→0008 线性完整无分叉，均带 downgrade（0004 的 no-op 有数据
  不可逆的文档说明）。
- llm.py 无 API key 泄漏路径（Authorization 不进日志/异常文本）。
- 优先修复建议：**A0（默认 Docker 部署下 Web 扫描全灭，修法已实测）**、
  A1/A2（增量失效 + CLI 落库回归，两个都是「已修过的 bug 在另一条路径上
  复活」）、A4/A5（直接影响误报率与覆盖率铁律）、B11/B13（公网化前必须
  修）、C17/C18（Render 部署的静默丢数据与死配置）。

### G. 本地运行记录（2026-10-25，WSL2 Debian 13 + Docker，供复现）

- 环境：WSL2 Debian trixie（systemd 开启），`get.docker.com --mirror Aliyun`
  装 docker-ce 29.7.2 + compose v5.5.0；宿主 TUN 代理下 `python:3.12-slim`
  直拉 24s，无需 registry-mirrors。
- 代码放 WSL 原生文件系统（`~/SEO-Claw`）构建——`/mnt/d` 跨 9p + 中文
  路径构建慢；仓库无 `.gitattributes`，Windows 检出的 `.sh` 是 CRLF，
  WSL 里直接跑会报 `$'\r'`（见 C21）。
- `docker compose up -d --build` → 容器 healthy → `/api/v1/health` 200 →
  Windows 侧 `http://127.0.0.1:8000` 200（WSL localhost 转发可用）。
- ⚠️ **TUN fake-IP 与 SSRF 守卫互斥**：代理把所有域名解析到
  198.18.0.0/15（A 记录）/ 2001:2::/48（AAAA），守卫按「保留网段 =
  DNS rebinding 特征」正确拒绝——**这是守卫在干活，不是 bug**。要扫
  外网域名需在代理端给目标域配 fake-ip-filter（或直连规则）；演示时
  用 DoH 拿真实 IP 写容器 /etc/hosts 绕过（`docker exec -u root`——
  容器按设计非 root 运行，普通 exec 写不了）。
- ⚠️ **WSL VM 空闲关机**：无会话时约 1 分钟 VM 退出，容器随 VM 停、
  下次唤醒自动拉起（restart: unless-stopped，数据在卷里不丢）。日常用
  保持一个 WSL 终端开着，或在 `%UserProfile%\.wslconfig` 调
  `vmIdleTimeout`。
