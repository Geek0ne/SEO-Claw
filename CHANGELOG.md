# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增（Web 界面补上四处「后端有、界面没接」的入口）
- **日级排名导入、SERP 快照导入、定时托管复扫、整改工单导出**四处能力现在在界面里
  都能用了。四处都不是新功能——后端与 CLI 早就具备（2026-10-18 / 10-20 / 10-22），
  缺的是接线；能力存在但只有会 curl 的人用得到，等于没做。落点分别是
  「排名监测」「内容 Brief」「概览」「报告与导出」四页，导入侧一律配**回读表**，
  让用户自己查得到「导进去了没有」，而不是信一句 toast。
- **两个新的原始文本端点**：`POST /sites/{id}/rankings/import` 与
  `POST /sites/{id}/serp/import` 收用户手里的 GSC / SERP 导出原文（选文件或粘贴）。
  ⚠️ 界面**一个字段都不解析**：表头别名、日期格式、坏行判定在 `rankdata` /
  `serpdata` 里各只有一份，前端再写一套的收场必然是「CLI 导得进、网页导不进」，
  而用户没能力判断哪套口径对。JSON 还是 CSV 的判定也收成唯一一份
  （`serpdata.detect_format`），CLI 与界面共用——界面拿到的是 `FileReader` 的纯文本，
  没有后缀可问，各判各的就会分叉。
- 请求侧上限统一写在 `api/schemas.py`：排名 5000 行 / SERP 50 组 / 原始文本 2 MB，
  超限报 422「请分批」；逐行失败原因最多回 200 条并**明说被截断了多少条**，
  界面上的折叠清单同样必须写总数。
- **抓取时刻这个字段在界面上改对了说法**：`SerpIngestOut.captured_at` 是
  **没带时间的那几组的兜底时刻**，不是「这批数据的抓取时间」。原来写成
  「这批的抓取时刻」，会把文件里标 10-20 的快照说成 10-22——字段语义在
  `schemas.py` 补了注释，界面标签改成「没写抓取时间的那几组按 … 落库」，
  并把真实落库值交给回读表。
- **一条不变量用例**：`test_web.py::test_every_api_path_the_page_uses_is_a_real_route`
  把页面上 JS 写到的每条 `/api/v1/...` 路径拿去和 `app.openapi()` 真实注册的路径
  逐条核对。查中文字面量只能证明卡存在，证明不了接线。⚠️ 取数必须走 OpenAPI：
  API 路由挂在子应用上，裸 `app.routes` 一条 API 路径都看不到（第一版就是这么红的，
  红的是取数方式不是页面）。
- 数字随本轮变化：REST **30 个路径 / 38 个操作**（此前 28/36）、测试 **737 个**、
  覆盖率 **80.0%**（门禁 78% 不动）。`api/routes.py` 仍报 37%——新增的两个端点
  确实被用例打到，但比例被同批新增行数摊平，这条缺口照旧记在 PLAN 技术债里。

### 变更（产品决策落档 · M0 性能指标作废）
- **M0「1000 URL ≤5 分钟」这条硬指标作废，默认 3 req/s 保持不动**。实测 382s
  （6.4 分钟）超原线，但归因清楚：`per_domain_rps=3.0` 让 1000 页的墙钟下界是
  333s（占实测 87%），限速器串行放行，**加并发压不下去**；要达标只剩「把默认
  rps 提到 ≥3.34」，代价是对第三方站更激进、被封概率上升。**取舍：礼貌优先，
  数字改成引用实测**。今后对外说「1000 页 ≈ 6.4 分钟（3 rps 上限下的物理结果）」，
  不要再说「应该 5 分钟」。README 中英两份与 `PLAN.md` M0 清单同步。
- **SERP 代抓（自动拉竞品位次）明确延后到盈利之后**：本轮只交付入口
  （用户/跟踪器/SERP API 导出 → 落库），代抓要接付费第三方，没有收入就引入
  固定成本不合理。重启条件写在 `PLAN.md` P2 #15。
- **API Key 那套定性保留**：只存哈希 + 签发/撤销 + 额度 + 用量事件 + 站点归属
  验证，是《商业模式方案》模式二「不改内核，只加鉴权和配额」的现成底座，也是
  企业版「API 访问权限」溢价项的实现；缺的是档位→阈值的定价映射，不是新机制。
- **多租户 / RBAC 定了分步走**：第一步是「账号-站点归属 + 数据隔离」的最小闭环，
  角色表（owner/editor/viewer）等**第二个付费席位**出现再建——《产品手册》的
  团队协作 +¥20/月/席位 才是它的商业触发点，而 RBAC、审计、私有部署都挂在
  企业版与定制企业版（12 个月+）那一档。⚠️ 同时记下商业手册**超前于实现**的
  三处承诺：RBAC「没有」、操作审计只有计量用的 `usage_events`、
  「API 密钥 AES-256 加密」与实现的**只存哈希**不一致（哈希不可逆、比加密强，
  代价是明文只在签发那一次返回）——销售口径要么补齐要么改文档，别让它跑在代码前面。
- **GEO 实验包维持默认不加载**：继续 `--market geo` 点名启用，方法论验证做完前
  不进 `default_registry()`，以免证据强度较弱的规则污染 base 的 97.0% 准确率基线。

### 修复（CLI 入口的文件错误不再抛栈）
- **`rank-import` / `serp-import` 给个拼错的文件名，以前是一整屏
  `FileNotFoundError` traceback**，现在是一句人话 + 退出码 1。两处入口共用
  `_read_input_file()`：`-` 走标准输入（不再被当成名叫 `-` 的文件），其余按
  「文件不存在 / 那是个目录 / 不像文本文件（提示导出 UTF-8）/ 其他 OSError」
  分类打 stderr。⚠️ 跨平台细节：**读目录在 Windows 上抛 `PermissionError(13)`，
  POSIX 上才抛 `IsADirectoryError(EISDIR)`**——只靠 except 分支会导致同一句提示
  在两个系统上长得不一样（用例一边绿一边红），所以先自己 `is_dir()` 判、再兜异常。
  四条新用例钉住：拼错路径、给目录、二进制文件、`-` 读标准输入（含「错误路径不该
  碰库」的副作用检查）。`cli.py` 覆盖率 38% → **41%**。

### 新增（README 宣传数字的回归网）
- `test_docs_stats.py`：把门面话钉到代码实数上——README 说的**表数与表名**
  对着 `Base.metadata.tables` 核（只核个数不够：漏一张、多一张、名字写旧了，
  个数都可能碰巧对）；**「28 个路径、36 个操作」**对着 `app.openapi()` 实数核，
  并明确弃用含义模糊的「端点」这种数法；**测试数与覆盖率徽标**要求徽标、中文
  正文、英文注释三处彼此一致（历史上漂过两次：中英各写 657 / 618，覆盖率徽标
  停在历史峰值 82%）；语言入口按口径钉住「中文 README 用 `[English](README.en.md)`、
  英文 README 必须指回 `README.md`」。非源码检出环境（只装 wheel 的容器）整组跳过。

### 新增（CLI 命令级用例 · 补薄接线层的测试）
- `test_cli_persist.py` 加四条命令级用例，`cli.py` 覆盖率 28% → **38%**，
  全量 726 测试 / 80.2%（门禁 78%，余量 2.2 个点）：
  - `rank-import` 端到端：GSC 风格别名表头（`page` / `average position`）与列序
    无关、坏日期逐行报号、重跑不涨行、**位次留空落成 NULL 而不是 0**、
    `www.` 剥掉后推断出域名、站点不在库里时给下一步。
  - 推不出域名 → 明确要求 `--site`。触发用的是 `https://` 这种「有协议没主机」
    的畸形导出：它校验得过（只要求完整地址前缀），但 `netloc` 为空，正是
    自动推断会失手的形状。
  - `rules` 按注册表实况**逐条比对**输出：漏一个市场或写死清单，就会让某包的
    规则「已注册但看不见」（cnh_eco 踩过）；同时钉住 geo 的规则**不在**清单里、
    而「默认不加载 + 怎么启用」的说明必须在。
  - `main([...])` 派发：parser 的默认值要和命令函数收到的对得上，
    缺必填 `--db` 由 argparse 以退出码 2 拦下，不该走进命令体。
- ⚠️ 补这批用例时发现一处粗糙：`rank-import` / `serp-import` 的文件参数给不存在
  的路径时，`Path.read_text()` 直接把 `FileNotFoundError` 的 traceback 糊在用户脸上。
  当轮按「只补测试、不动实现」的边界记入 `PLAN.md` 技术债，**下一轮已修**，
  见本文件上方「修复（CLI 入口的文件错误不再抛栈）」。

### 新增（SERP 快照数据入口 · 阶段 4）
- **`serpdata.py`：内容 Brief 的竞品维度从「永远为空」变成「导一次就有」**。
  `serp_snapshots` 表从 M0 就在 schema 里，但**没有任何路径能往里写**——
  `latest_for_keyword()` 恒空，Brief 的 Top10 共性一律走「竞品数据缺失」分支，
  caveat 只说「没有记录」而不说**怎么才会有记录**（用户无从下手）；同一份
  Brief 里「我方当前排名」那行还硬编码着「需接 Search Console」，而排名入口
  早在 `rank-import` 就通了——把已经接得到的数据说成没接，是另一种谎报。
  - CLI：`seoclaw serp-import <csv|json> --db seo.db --site example.com`；
    API：`POST /api/v1/sites/{id}/serp`（201）+ `GET .../serp?keyword=&market=&limit=`。
  - CSV 与 JSON 共用同一份校验（`result_from_fields` / `capture_from_fields`），
    坏行逐行报行号、坏组逐组报组号，好行照常入库——错误比 DB 层的错误便宜。
  - `position` 必须是**正整数名次**。小数的「平均排名」属于排名时序，请走
    `rank-import`；两种口径混进一张表，位次字段会被搜索量、竞品数之类的数字
    污染，Top N 就废了。这里选择拒收，不做「兼容」。
  - `--site` **必填**，不按 URL 猜域名：一次抓取里竞品域名占多数，
    「出现最多的 host」自动匹配会把数据灌到竞品名下。
  - 文件没写抓取时间 → 记为「今天 00:00 UTC」的一次快照，并把这条归一
    **当场打印**：跨自然日重跑同一份文件是「新增一次抓取」而不是「更新」，
    用户不知道这一点就会以为历史被重复了。
  - 一次抓取里一条标题都没有 → warning 而非 error：共性算不出来必须说，
    但不足以把整份位次数据拒了。
- **仓库层补 `SerpRepository.upsert` / `recent`**。幂等键
  `(keyword_id, captured_at, url)`，且**微秒不参与幂等键**：导出方的时间戳
  带本地时钟微秒，第二次导出就变了，认它等于每次重跑都新增一份伪历史，
  把真历史挤出 `latest_for_keyword`。`recent()` 一次 join 带回关键词原文——
  异步会话下靠关系属性取 `keyword.term` 会 `MissingGreenlet`。
  ⚠️ 此前 `bulk_create` 的注释写着「靠唯一约束变成幂等 upsert」，实现却是
  无脑 INSERT，重跑同一份导出直接撞 `IntegrityError`。**注释是谎报不是省略**，
  实现与用例一并补上。
- **Brief 真的消费 SERP 数据**：`market` 参与取词（此前只按 term 查，
  同一个词在 baidu / google 下会串数据）；`not_available` 文案改为指向
  `serp-import`；`POST /brief` 的 `market` 只认四个已知市场，其余 422。
- **Brief 新增 `own_rank`**：我方当前排名从 `rank_history` 取该 URL 最近一个
  有 `position` 的日期；取不到就明说不可用并给出补救路径，不写「排名 0」
  （0 既不是名次也不是「没有」）。

### 修复（分支收敛后的类型检查与测试隔离）
- **`test_web.py` 的 DNS 打桩改为一个真查询都不发**。开发机上代理的 fake-IP
  模式（198.18.0.0/15 基准测试网段）会把 `example.com` 也解析成保留网段地址，
  SSRF 守卫拒得对（400），但「测试过不过」就此取决于本机开没开代理。
  守卫自身的解析/拒绝用例在 `test_guard.py` 逐条控制解析结果。
- **「同域不重复建站」那条改为翻页查**（`?limit=200&offset=N`）。列表默认
  只给 50 条，套件建站数早已过一页，只看第一页得到空列表——症状是
  「单文件跑绿、全量跑红」。
- **mypy 存量 10 处归零**（`fixpack.py` / `rankdata.py`）：`_fix_*` 系列返回
  的「改前」实际会是 `None`（那正是「这页压根没有这个字段」）而签名写着
  `str`；`Counter()` 缺参数化标注；`RENDERERS` 被两个 lambda 的签名绑架推断。
  另删掉 `_detect_site_suffix` 里永不成立的 `(None, 0)` 假分支。
  门槛口径见 `pyproject.toml [tool.mypy]`：**类型检查扫的恰是测试的盲区**。
- 三处 `__import__("fastapi").Depends(get_uow)` 改回 `Depends(get_uow)`。
- **`serp-import` 的两处输出缺陷是人肉冒烟跑出来的**（已补命令级用例
  `test_serp_import_cli_end_to_end` 钉住，真文件 + 真临时库）：
  - 混合文件（部分行带抓取时间、部分不带）时，「按今天 00:00 UTC 记一次
    快照」这句归一说明**整段不打印**——判据写成了「整个文件都没给时刻」，
    而被补了默认时刻的那几组恰恰最需要被告知。改成按「没给时刻的组数」计数。
  - 零标题的提示写成「Top1 条结果一条标题都没有」，那个 `Top` 是多余的，
    读起来像在报名次；改成「1 条结果里一条标题都没有」。
  这两条都在解析层与落库层的用例之外：它们绿着，命令照样说错话。
- **分支收敛**：master 上的阶段 1 / 2a / 2b / 3（结构化日志 + CI mypy、
  持久任务队列、定时复扫调度、Top 5 口径统一）合回 main，master 删除，
  此后只有一条 main。两边的活儿都收进来再删——直接以 main 为准会丢掉
  约 2,400 行实现与 555 行测试。详见 PLAN「当前状态」。

### 新增（整改工单 / 排名数据入口 / 白标交付）
- **整改工单（处方包，`fixpack.py`）**：把规则命中转成「改前 → 改后」的
  可落地修复动作，产品从「体检报告」跨到「照着改的工单」。
  - 处方分三档可信度并**强制展示**：`deterministic`（自指 canonical /
    viewport 常量 / 按文件名起草 alt）、`heuristic`（title/meta/h1 机器
    起草，标注「发布前请人工润色」）、`recipe`（robots/sitemap/JSON-LD/OG
    只给配方）。判不了的进 `manual_review` 带原 fix_hint，**不硬凑**。
  - 输出四格式：`md`（工单）/ `json` / `csv`（派工表）/ `diff`（逐页
    unified diff，给模板工程师照着改）。
  - CLI：`scan --fixpack out.md`；API：`GET /api/v1/sites/{id}/fixpack`。
    Web 版是库重建口径，边界（img_alt 类仅 CLI 可出）写进工单自己的
    「工单说明」，不靠口头声明。
  - 站点级问题（title.duplicate / meta.duplicate）按页面集合**逐页归因**：
    报告可以说「N 页重复」，工单必须落到「哪个页面改成什么」。
- **排名数据入口（`rankdata.py`）**：监测闭环断在入口——`rank_history` 表、
  幂等 upsert、跌落告警早就写好，但没有任何路径能把数据灌进去。
  - CLI：`seoclaw rank-import <csv> --db seo.db`；API：
    `POST /api/v1/sites/{id}/rankings` + `GET .../rankings`。
  - 列名认别名（page/address/average position/query…），`5%` 与 `0.05`
    两种 ctr 写法都认；坏行跳过并**逐行报行号**，好行照常入库。
  - `position` 留空 = 「当天没排名数据」≠「排最后」，入口不抹平这个区分。
  - ⚠️ GSC 网页版导出是区间聚合（无日期列），直接拒绝并提示用日级数据源
    ——假时序画真趋势比不画更糟。
  - 校验规则只有一份（`row_from_fields`），CSV 与 API 共用。
- **白标交付**：`scan --brand 名字`，报告与工单落款换成代理商的品牌
  （P3 客户的付费点）；不给则保持 SEO-Claw 署名。

### 修复（阶段 3：Top 5 优先做，全出口同一口径）
- **「先做清单」三处口径分叉全部修齐**。此前：终端/Markdown/HTML 报告
  按「严重度 × 影响面」排（scoring.top_actions），**网页自己按严重级排前
  5**，**CLI `--json` 和 API `/report`（Web+MCP 共用）压根没有 Top 5**——
  同一次扫描三处「先做」对不上，用户没理由知道该信哪个。现在排序只有
  scoring 一份实现，`build_summary` 与 `json_payload` 只做序列化。
- **API 问题条目补上「可执行改法」三件套**（description/impact/
  fix_hint/fix_example）：此前 IssueOut 不给这些字段，网页声称的
  「每条带怎么改+示例」实际渲染不出来。top_actions 条目另带
  affected_pages（该问题影响几页——排「先做」的核心输入）。
- 网页「最该先做的事」改读服务端 top_actions，条目展示影响页数、
  影响说明、怎么修、可复制示例。
- M0 验收项关闭：真站实测 antfu.me（5 页/13 问题）Top 5 全部带改法。
- 顺手修 mypy 两处（stage 2b 的 dict 字面量推断、top_actions 装配的
  dict 注解）；ruff 零告警、mypy 零错误、650 测试全绿。

### 新增（阶段 2b：定时扫描调度）
- **托管定时复扫**：站点声明复扫间隔（`sites` 三列，迁移 0008：
  `scan_interval_s` / `next_scan_at` / `schedule_params`），调度器
  `scheduler.py` 到期自动入队，走阶段 2a 的持久队列执行。API 两端点：
  `PUT /sites/{id}/schedule`（`interval_s=null` 停用；正整数开启且
  **首个周期立即到期**）、`GET /sites/{id}/schedule`。
- 调度语义四条，各有测试钉着：①**at-most-once**（CAS 认领与入队同事务、
  认领在前，崩掉宁漏勿双）；②**不叠任务**（有 pending/running 就跳过
  入队但照常推进周期，按时间节奏走，扫描比周期长时队列不会越积越多）；
  ③**参数定格**（执行参数读开启托管时的快照，不实时读站点设置）；
  ④**队列满不认领**（留在 due 下个 tick 再试，与 web 端拒收同一条
  「排队承诺必须兑现」的底线）。
- `ScanTaskRepository.has_active`；`SiteRepository` 的
  `set_schedule` / `due_schedules` / `claim_schedule`（CAS：条件 UPDATE
  `next_scan_at <= now` 看 rowcount，与 claim_next 同套路）。
- 测试 `test_scheduler.py`：tick 语义 8 条 + API 5 条 + **接线 1 条**
  （拉小轮询间隔等 lifespan 跑的 scheduler_loop 自己触发——只测
  tick 不测接线，就存在「函数全对、没接上电」的空隙）。
- 托管最小间隔 1 小时（`MIN_SCHEDULE_INTERVAL_S`）：扫描本身就要
  几分钟到几十分钟，下限是爬虫礼仪不是技术参数。
- **踩坑一枚（收尾吊死）**：lifespan 收尾原本无界 `await` 被取消的
  worker，而取消落在 SQLAlchemy 异步驱动的 greenlet 交接区时，任务会
  吊死在没人置位的 future 上（实测栈：aiosqlite `_terminate_graceful_close`
  的 `asyncio.shield`，线程已空闲、close future 永远不完成）——
  **症状是测试套件随机挂起**，挂哪条取决于取消命中哪个 DB 操作（快速
  开关 TestClient 基本必中：启动时连续几个 DB 调用，首关就撞窗口）。
  修法是收尾**有界等待**（2s 到点就走，dispose 同理用 task+wait 而非
  wait_for——后者超时后还会等取消完成，对吊死任务同样永久挂住），
  回归钉 `test_rapid_client_cycles_do_not_wedge_shutdown`（线程+join
  超时，真回归时 FAIL 而不是把套件挂死）。上游 interplay 不在本仓
  可修范围，边界防御到此为止。

### 新增（阶段 2a：持久任务队列）
- **任务队列落库**：`scan_tasks` 表（迁移 0007）+ `seoclaw/tasks.py` 执行器。
  Web 体检任务从进程内存（`_TASKS`/`_INFLIGHT`/`_NEXT_ID`）迁到数据库：
  重启不丢、多 worker 安全（原子认领：条件 UPDATE 看 rowcount，抢不到就让），
  被杀进程的孤儿任务由启动恢复捞回（attempts 未超限重排、超限标 failed，
  绝不留永远 running 的行）。同进程提交唤醒秒级开跑，跨进程靠慢轮询兜底；
  队列深度上限 50 拒收——排队承诺必须兑现。
- 迁移 0007；模型/迁移零漂移（alembic check 干净）。

### 修复
- `asyncio.Event` 在模块 import 时创建会绑死事件循环：第二个 TestClient
  的新循环一碰就是「bound to a different event loop」。改为按循环惰性重建。
- 重排队任务的 elapsed 拿 created_at 算，报出过 2 亿秒——没开跑现在报 0，
  elapsed 只认 started_at（排队时长和运行时长是两个量）。
- `@dataclass(slots=True)` 装饰器被新类插队接住（症状：`self.session = session`
  报 no attribute——slots 的经典面孔），装饰器已归位。

### 变更
- **Web 语义**：并发满不再当场 503，改为排队（现在真的有队列，这个
  承诺才兑现得了）；队列深度满才拒。
- 旧内存态用例重写为落库等价物：inflight 释放×3 → running 行清零×2 +
  孤儿恢复；并发上限拒收 → 队列上限拒收。

## [阶段 1 已随 49f5367 提交]

### 新增
- **结构化日志 `seoclaw/log.py`**：JSON/文本双格式（`SEO_CLAW_LOG_FORMAT=json`）、
  级别环境变量（`SEO_CLAW_LOG_LEVEL`）、`extra=` 字段并进 JSON 顶层便于检索。
  `main.py` lifespan 统一接线；scan_service 与 web 任务生命周期
  （提交/完成/失败/并发满被拒）全部留痕。此前服务端排障全靠 print(stderr)。
- **CI 增加 mypy 任务** + `pyproject.toml [tool.mypy]`。PLAN.md 质量表写着
  「mypy strict 零错误」而 CI 里一直没有 mypy——先钉默认严格度归零
  （31 → 0），strict 作为后续棘轮逐步开，不一步到位后批量加 ignore 自欺。
- 测试：`test_log.py`（日志契约：JSON 形状 / extra / configure 幂等）、
  `test_api.py::test_keywords_expand_happy_path`（正常路径回归，见下）。

### 修复
- **关键词扩展端点正常路径从未走通过**：`routes.py` 里 `kw_expand.expand(...)`
  把**函数**当模块调（`keywords/__init__` 把函数绑在包命名空间），一到正常
  路径就 AttributeError。既有测试全绿只因用例停在 skipped_* 提前返回分支，
  离崩溃点差一步。由 mypy 发现（“def expand has no attribute expand”），
  现改为显式子模块导入，并补正常路径回归测试。
- **Web 扫描的站点级事实恒空**：`scan_service._crawl_and_audit` 里另起一只
  全新 Crawler 当“verifier”喂给 `_collect_site_facts`——它 sitemap_result 是
  None、robots 从没被探过，sitemap/robots 类站点级规则在 Web 扫描里永远
  拿不到事实（CLI 是就地取材的，两处口径分叉很久）。现改为取自抓过站的
  那只爬虫，并补上 `hit_page_limit`（旧代码连这个键都没赋）。
- `cli.py` AI 总结块把 `cfg` 复用给 LLMConfig（同函数上方已有
  `cfg = CrawlConfig`）——同名复用悄悄覆盖爬虫配置。改名 `llm_cfg`。
- baidu ICP 规则对同一文本正则搜两次、第二次不判 None 直接 `.group(0)`。
- `brief.py` 拿 `Optional[Intent]` 当 dict 键 `.get()`（运行时靠巧合落默认值）。
- `keywords/expand.py` ngram 统计注解写成 `Counter[str]`，实际值是 URL 集合。

### 重构
- **同名不同义的 `domain_of` 拆开**：`util.domain_of`（去 www，评分/报告口径）
  与 `persist.netloc_of`（保留原始 netloc，归一化交仓储）。两者曾分别叫
  `scan_service._domain_of` / `persist.domain_of`，同名不同义是踩坑温床。
- `routes.py` 清掉 26 处 `__import__("fastapi").Depends(get_uow)` 技巧，
  改为正规导入 `Depends`。
- `db/repository.py`：DML 行数统一走 `_rowcount()`（`AsyncSession.execute`
  的 stub 只标 `Result`，rowcount 在 CursorResult 上）；类内返回注解用
  `builtins.list`（类方法 `list` 遮蔽内建 list，mypy 解析成方法）。

### 工程地基（阶段 1）小结
本阶段以“mypy 钉零”为抓手扫了一遍类型盲区，顺手挖出两个真 bug——
**都是单测全绿、接口通、答案错/路径断的类型**：测试覆盖面的盲区
（正常路径没测）恰好是 mypy 的强项。630 测试全绿、ruff 零告警、
mypy 零错误后入库。
- **CI lint 任务**（ruff check）：PLAN.md 质量保障表一直写着「ruff 零告警」，
  但 CI 里根本没有 lint 任务，门槛写在文档里等于没写。规则集只查真问题
  （E4/E7/E9/F），不开行长、不上格式化——注释文化经不起格式化工具重排。
- `pyproject.toml` 的 `[tool.ruff]` 配置（含测试文件 E402 豁免：环境变量
  必须在 import seoclaw.* 之前设，见 test_api.py 文件头）。

### 修复
- **静态检查清零：65 条告警 → 0**（未用导入 / 未用变量 / 歧义命名 `l` /
  无占位 f-string）。其中两条不是纯卫生问题：
  - `api/routes.py` brief 端点的 `site` 变量：`_require_site` 的返回值没接，
    但那个调用本身就是归属校验，改为显式不接收返回值，免得后人当死代码删掉。
  - `google` 包 lang 规则的 `verdict` 局部变量算了没用，实际方向
    （declared_latin_but_content_cjk 等）从未进证据；现以 `mismatch_type`
    入 evidence，用户可自核「哪个方向对不上」。
- `scripts/accuracy_run.py` 重试循环里的 `last` 变量同 `sc`，删净。
- **`alembic check` 模型/迁移漂移**（仓库自带，PLAN.md 却声称「零漂移」）：
  迁移 0006 给存量 `sites` 表 ADD COLUMN 时给 `owner`/`verify_status` 设了
  `server_default`，模型只写了 Python 侧 `default=` —— 两边不一致，
  `alembic check` 报 modify_default。模型补 `server_default` 对齐库里实态，
  现在 `alembic upgrade head && alembic check` 全干净。

### 重构
- **清偿技术债：像素宽度表不再两包各存一份**。上提到中立模块
  `audit/rules/_serp_px.py`（不 import 任何规则包，不会触发
  google.i18n → google → baidu 的环引用），google/baidu 共用同一张表，
  删除「改 google 必须同步 baidu」的人工约定。指标值不变
  （test_fp_baidu_2026 的像素断言钉着）。

## [0.2.0] - 2026-10-10

### 变更（Breaking-ish）
- **项目更名为 SEO-Claw**：发行包名 `seo-claw`，CLI 命令 `seo-claw`
  （`seoclaw` 保留为兼容别名）；Python 导入包名不变（模块名不能带连字符）。
- **仓库结构扁平化**：项目文件从 `SEOClaw/` 子目录上移到仓库根。
  GitHub 首页现在能直接渲染 README，CI 路径全部生效
  （此前 `.github/workflows/` 在子目录里，**CI 实际上从未运行过**）。
- `--market` 新增实验性取值 `geo`（AI 搜索引用性）。此前 README 宣称支持
  但 CLI 直接报 invalid choice——geo 规则包没有任何入口。现在点名才加载，
  默认注册表与默认扫描保持不含 geo。

### 新增
- LICENSE 文件（MIT）。此前只有文档声明，法律上不成立。
- `seoclaw --version`。
- CONTRIBUTING.md / SECURITY.md / CHANGELOG.md / README.en.md。
- `mcp` 可选依赖组（`pip install -e ".[mcp]"`），MCP 测试不再永远跳过。
- pytest `testpaths` 修正为 `backend/tests`（裸跑 `pytest` 可用）。

### 修复
- README 中过时的数字全部更正（测试数、代码行数、数据库表数、规则包条数）。

### 仓库卫生
- `reports/` 只保留验证证据三件（`fp_json_v3/`、`calib_json/`、
  `verify_verdict.md`），其余中间产物移出版本库并加入 `.gitignore`。

## [0.1.0] - 2026-10

首个可用版本（详见 git 历史）：

- 规则引擎：base 22 条 + google 11 + baidu 5 + cnh_eco 1（+ 实验包 geo 4），
  页面级 / 站点级分层，覆盖率不足自动沉默。
- BFS 爬虫：限速、自适应降速、熔断、代理轮换、断点续传、ETag/304 增量。
- 报告：终端 / Markdown / JSON / 单文件 HTML。
- 持久化：12 表 + Alembic 迁移（SQLite / PostgreSQL）。
- Web 服务：quick-scan + 进度轮询，多租户 API Key、额度、站点归属验证。
- 关词模块（纯离线）、内容 Brief、可选 LLM 总结、MCP Server（3 个只读工具）。
- 回源核验体系：`tools/verify_*.py` + `docs/verification-ledger.md`。
