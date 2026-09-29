# SEO 体检报告 · go.dev

扫描时间：2026-09-29 11:56 UTC · 耗时 18s · 抓取 5 / 发现 283 个 URL

## 健康分：76 / 100

共 17 个问题：🔴 严重 0 · 🟠 高 6 · 🟡 中 5 · 🔵 低 5

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 100 |
| 信息架构 | 100 |
| 页面内容质量 | 77 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [高] 页面缺少 meta description

description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。

**怎么修**：补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。

```html
<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">
```

**证据**：

- `meta_description_found` = `False`

### 2. [高] 站点没有可用的 sitemap

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

### 3. [中] 图片缺少 alt 文本

alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。

**怎么修**：补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。

```html
<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">
```

**证据**：

- `missing_count` = `16`
- `total_images` = `56`
- `sample_srcs` = `['https://go.dev/images/logos/social/google-groups.svg', 'https://go.dev/images/logos/social/github.svg', 'https://go.dev/images/logos/social/bluesky.svg', 'https://go.dev/images/logos/social/masto...`

### 4. [高] 页面没有 H1 标题

H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。

**怎么修**：加一个 H1 写清页面主标题，位置放在正文开头。

**证据**：

- `h1_count` = `0`

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

### 🟠 高（6 处，3 类）

- **meta.missing** — 页面缺少 meta description · 影响 4 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://go.dev/learn/
  - 示例：https://go.dev/security/
  - 示例：https://go.dev/solutions/case-studies
  - ……另有 1 个
- **h1.missing** — 页面没有 H1 标题 · `https://go.dev/solutions/case-studies`
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://go.dev/solutions/case-studies
- **sitemap.missing** — 站点没有可用的 sitemap · 全站

### 🟡 中（5 处，1 类）

- **img.alt.missing** — 图片缺少 alt 文本 · 影响 5 个页面
  - 示例：https://go.dev/
  - 示例：https://go.dev/learn/
  - 示例：https://go.dev/security/
  - ……另有 2 个

### 🔵 低（5 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 5 个页面
  - 示例：https://go.dev/
  - 示例：https://go.dev/learn/
  - 示例：https://go.dev/security/
  - ……另有 2 个

### ⚪ 提示（1 处，1 类）

- **soft404** — 疑似软 404（需确认） · `https://go.dev/solutions/use-cases`
  - 示例：https://go.dev/solutions/use-cases
