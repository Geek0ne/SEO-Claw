# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
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
