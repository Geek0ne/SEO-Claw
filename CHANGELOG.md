# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

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
