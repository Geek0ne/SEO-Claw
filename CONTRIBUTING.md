# 参与贡献

感谢关注 SEO-Claw。这个项目的立身之本是**「只报有正面证据的问题」**——
贡献前请先认同这条，其余约定都从它推导而来。

## 开发环境

```bash
git clone https://github.com/Geek0ne/SEOClaw.git
cd SEOClaw
pip install -e ".[api,dev]"
pytest backend/tests -q
```

要求 Python 3.11+（CI 环境为 3.12）。改动 Web/API 层时把 `api` extra 装上；
测试 MCP 层需要 `pip install -e ".[mcp]"`。

## 提交前的硬性检查

```bash
pytest backend/tests -q          # 全量测试，必须全绿
python -m seoclaw.cli rules      # 规则注册表能正常列出
python -m build --wheel          # 包能构建
```

改动 Web / 鉴权 / 限额相关代码时，还需跑真容器验收：

```bash
./tools/guard_smoke.sh           # 四道闸：SSRF / 限流 / 并发 / 黑名单
```

CI 会重复以上全部步骤，并卡覆盖率（当前约 82%，门禁 78%）。

## 新增检查项（规则）

1. 在 `backend/seoclaw/audit/rules/<market>/` 下新建规则类，`code` 全局唯一；
2. **必须能给出正面证据**——「未检出」不能直接推出「不存在」。若判据是
   「没看到 X」，先回答：JS 渲染、抓取失败、覆盖率不足时它会不会误报？
3. `severity` 从严：拿不准就低一级；「可能是站方有意为之」的结论标
   `possibly_intentional` 并降为 INFO；
4. 为它写**回源核对**：能实跑站点验证的，把证据与结论记进
   `docs/verification-ledger.md`；
5. 补测试——包括**不该报**的场景（误报测试比命中测试更有价值）。

实验性规则放 `geo` 这类独立包，**不要**进 `base`：已验证规则与未验证规则
必须物理隔离（这是 `--market geo` 显式加载机制存在的原因）。

## 代码风格

- 注释写**为什么**，不写做了什么。踩过的坑写进注释——这个仓库的注释
  大多是事故记录，请延续这个习惯；
- 不引重依赖。`llm.py` 用 httpx 直连 OpenAI 兼容端点而不是引 litellm，
  是有意的取舍；
- 破坏性操作（删数据、改迁移）先开 issue 讨论。

## 提交信息

沿用现有风格：`类型(范围): 一句话结论`，如
`fix(rules): sitemap 索引判据改为看根元素，修 12/58 假阳性`。
正文写清楚「为什么」和「怎么验的」。

## 行为准则

不骚扰、不歧视、不人身攻击。技术分歧就事论事。
