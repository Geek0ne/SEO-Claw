# SEO 体检报告 · overreacted.io

扫描时间：2026-09-29 08:35 UTC · 耗时 13s · 抓取 8 / 发现 74 个 URL

## 健康分：92 / 100

共 16 个问题：🔴 严重 0 · 🟠 高 2 · 🟡 中 6 · 🔵 低 7

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 96 |
| 信息架构 | 100 |
| 页面内容质量 | 96 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [高] 站点没有可用的 sitemap

没有 sitemap 时，搜索引擎只能靠内链发现页面，新页面和深埋页面的收录速度会明显变慢，抓取预算也用得更浪费。

**怎么修**：生成 XML sitemap，在 robots.txt 里声明它，并提交到 Google Search Console 和百度搜索资源平台。

```html
User-agent: *
Allow: /
Sitemap: https://example.com/sitemap.xml
```

**证据**：

- `tried_paths` = `[]`
- `error` = `None`

### 2. [中] 页面缺少 canonical 标签

URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。

**怎么修**：在 <head> 里加 <link rel="canonical" href="本页的规范地址">。

```html
<link rel="canonical" href="https://example.com/product/123">
```

**证据**：

- `canonical_found` = `False`

### 3. [高] 页面没有 H1 标题

H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。

**怎么修**：加一个 H1 写清页面主标题，位置放在正文开头。

**证据**：

- `h1_count` = `0`

### 4. [低] 页面没有结构化数据

结构化数据让搜索引擎理解页面实体（商品、文章、FAQ），是拿到富媒体搜索结果的前提。

**怎么修**：按页面类型添加对应的 JSON-LD：商品页用 Product，文章页用 Article。

```html
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"防水登山鞋","offers":{"@type":"Offer","price":"299"}}
</script>
```

**证据**：

- `jsonld_count` = `0`
- `microdata_count` = `0`

### 5. [提示] 疑似软 404（需确认）

页面返回 200 但正文极少，搜索引擎会识别为软 404 并停止索引。⚠️ 但索引页、目录页、标签页天生内容少，不一定是问题——工具会提供判定信号，请确认：这个页面是“该有内容却没有”，还是“本身就是列表页”。

**怎么修**：如果确实是空页面：返回真正的 404 状态码，或补上内容。如果是索引/列表页：忽略本条即可。

**证据**：

- **verdict**: likely_index_or_hub
- **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
- `internal_outbound_links` = `59`
- `inbound_links` = `24`
- `url_looks_like_index` = `False`
- `word_count` = `100`
- `text_preview` = `How I Vibed a Proof of Conway’s Conjecture September 18, 2026 You can just prove things, apparently.`
- `status_code` = `200`

## 全部问题明细

### 🟠 高（2 处，2 类）

- **h1.missing** — 页面没有 H1 标题 · `https://overreacted.io/`
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://overreacted.io/
- **sitemap.missing** — 站点没有可用的 sitemap · 全站

### 🟡 中（6 处，1 类）

- **canonical.missing** — 页面缺少 canonical 标签 · 影响 6 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://overreacted.io/hire-me-in-japan/
  - 示例：https://overreacted.io/how-i-vibed-a-proof-of-conways-conjecture/
  - 示例：https://overreacted.io/how-to-fix-any-bug/
  - ……另有 3 个

### 🔵 低（7 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 7 个页面
  - 示例：https://overreacted.io/
  - 示例：https://overreacted.io/hire-me-in-japan/
  - 示例：https://overreacted.io/how-i-vibed-a-proof-of-conways-conjecture/
  - ……另有 4 个

### ⚪ 提示（1 处，1 类）

- **soft404** — 疑似软 404（需确认） · `https://overreacted.io/`
  - 示例：https://overreacted.io/
