# SEO 体检报告 · www.rust-lang.org

扫描时间：2026-09-29 05:35 UTC · 耗时 21s · 抓取 10 / 发现 647 个 URL

## 健康分：89 / 100

共 24 个问题：🔴 严重 0 · 🟠 高 3 · 🟡 中 11 · 🔵 低 10

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 95 |
| 信息架构 | 100 |
| 页面内容质量 | 95 |
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

### 4. [中] 多个页面 meta description 相同

相同的 description 让这些页面在搜索结果里长得一样，用户没有理由点开第二个。

**怎么修**：每页 description 描述该页面独有的内容与卖点。

**证据**：

- https://www.rust-lang.org/
- https://rust-lang.org/tools/install
- https://rust-lang.org/learn
- ……另有 5 个

### 5. [低] 页面没有结构化数据

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

## 全部问题明细

### 🟠 高（3）

- **h1.missing** — 页面没有 H1 标题 · `https://blog.rust-lang.org/`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://play.rust-lang.org/`
  - h1_count: `0`

- **sitemap.missing** — 站点没有可用的 sitemap · 全站
  - tried_paths: `[]`
  - error: `None`


### 🟡 中（11）

- **canonical.missing** — 页面缺少 canonical 标签 · `https://blog.rust-lang.org/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://play.rust-lang.org/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/community`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/funding`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/governance`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/learn`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/learn/get-started`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/tools`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://rust-lang.org/tools/install`
  - canonical_found: `False`

- **meta.duplicate** — 多个页面 meta description 相同 · 全站
  - 示例：https://www.rust-lang.org/
  - 示例：https://rust-lang.org/tools/install
  - 示例：https://rust-lang.org/learn
- **soft404** — 疑似软 404（需确认） · `https://play.rust-lang.org/`
  - **verdict**: uncertain
  - **verdict_explain**: 信号不明确，请人工看一眼
  - internal_outbound_links: `0`
  - inbound_links: `18`
  - url_looks_like_index: `False`
  - word_count: `15`
  - text_preview: `Rust Playground`
  - status_code: `200`


### 🔵 低（10）

- **schema.missing** — 页面没有结构化数据 · `https://blog.rust-lang.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://play.rust-lang.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/community`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/funding`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/governance`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/learn`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/learn/get-started`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/tools`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://rust-lang.org/tools/install`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://www.rust-lang.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

