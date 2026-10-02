# SEO 体检报告 · tailwindcss.com

扫描时间：2026-09-29 08:41 UTC · 耗时 11s · 抓取 6 / 发现 408 个 URL

## 健康分：87 / 100

共 16 个问题：🔴 严重 0 · 🟠 高 2 · 🟡 中 8 · 🔵 低 6

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 95 |
| 信息架构 | 100 |
| 页面内容质量 | 93 |
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

### 5. [中] 图片缺少 alt 文本

alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。

**怎么修**：补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。

```html
<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">
```

**证据**：

- `missing_count` = `2`
- `total_images` = `40`
- `sample_srcs` = `['https://tailwindcss.com/_next/static/media/dark-mode.light.0tx34lu8jwt_1.png', 'https://tailwindcss.com/_next/static/media/dark-mode.dark.11szx9d7s4zjz.png']`

## 全部问题明细

### 🟠 高（2 处，2 类）

- **h1.missing** — 页面没有 H1 标题 · `https://play.tailwindcss.com/`
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://play.tailwindcss.com/
- **sitemap.missing** — 站点没有可用的 sitemap · 全站

### 🟡 中（8 处，4 类）

- **canonical.missing** — 页面缺少 canonical 标签 · 影响 5 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://play.tailwindcss.com/
  - 示例：https://tailwindcss.com/blog
  - 示例：https://tailwindcss.com/docs
  - ……另有 2 个
- **img.alt.missing** — 图片缺少 alt 文本 · `https://tailwindcss.com/`
  - 示例：https://tailwindcss.com/
- **soft404** — 疑似软 404（需确认） · `https://play.tailwindcss.com/`
  - 示例：https://play.tailwindcss.com/
- **title.too_long** — title 过长会被截断 · `https://tailwindcss.com/`
  - **根因推测**：多个页面共用同一套 title
  - 这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，而不是把 title 加长到不报“过短”为止。
  - 示例：https://tailwindcss.com/

### 🔵 低（6 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 6 个页面
  - 示例：https://play.tailwindcss.com/
  - 示例：https://tailwindcss.com/
  - 示例：https://tailwindcss.com/blog
  - ……另有 3 个
