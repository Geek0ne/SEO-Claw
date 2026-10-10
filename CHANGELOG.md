# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
