# SEO 体检报告 · antfu.me

扫描时间：2026-09-29 07:57 UTC · 耗时 10s · 抓取 10 / 发现 185 个 URL

## 健康分：70 / 100

共 49 个问题：🔴 严重 0 · 🟠 高 15 · 🟡 中 11 · 🔵 低 20

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 95 |
| 信息架构 | 100 |
| 页面内容质量 | 76 |
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

### 2. [高] 页面没有 H1 标题

H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。

**怎么修**：加一个 H1 写清页面主标题，位置放在正文开头。

**证据**：

- `h1_count` = `0`

### 3. [高] 站点没有可用的 sitemap

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

### 4. [高] 多个页面 title 完全相同

重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。

**怎么修**：为每个页面写能体现其独特价值的 title，用页面主题词区分。

**证据**：

- https://antfu.me/
- https://antfu.me/posts
- https://antfu.me/projects
- ……另有 6 个

### 5. [中] 页面缺少 canonical 标签

URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。

**怎么修**：在 <head> 里加 <link rel="canonical" href="本页的规范地址">。

```html
<link rel="canonical" href="https://example.com/product/123">
```

**证据**：

- `canonical_found` = `False`

## 全部问题明细

### 🟠 高（15 处，4 类）

- **meta.missing** — 页面缺少 meta description · 影响 9 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://antfu.me/
  - 示例：https://antfu.me/demos
  - 示例：https://antfu.me/photos
  - ……另有 6 个
- **h1.missing** — 页面没有 H1 标题 · 影响 4 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://100.antfu.me/
  - 示例：https://antfu.me/photos
  - 示例：https://antfu.me/podcasts
  - ……另有 1 个
- **sitemap.missing** — 站点没有可用的 sitemap · 全站
- **title.duplicate** — 多个页面 title 完全相同 · 全站
  - **根因推测**：多个页面共用同一套 title
  - 这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，而不是把 title 加长到不报“过短”为止。

### 🟡 中（11 处，3 类）

- **canonical.missing** — 页面缺少 canonical 标签 · 影响 9 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://100.antfu.me/
  - 示例：https://antfu.me/demos
  - 示例：https://antfu.me/photos
  - ……另有 6 个
- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/photos`
  - 示例：https://antfu.me/photos
- **soft404** — 疑似软 404（需确认） · `https://100.antfu.me/`
  - 示例：https://100.antfu.me/

### 🔵 低（20 处，2 类）

- **schema.missing** — 页面没有结构化数据 · 影响 10 个页面
  - 示例：https://100.antfu.me/
  - 示例：https://antfu.me/
  - 示例：https://antfu.me/demos
  - ……另有 7 个
- **title.too_short** — title 过短，浪费了黄金位置 · 影响 10 个页面
  - **根因推测**：多个页面共用同一套 title
  - 这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，而不是把 title 加长到不报“过短”为止。
  - 示例：https://100.antfu.me/
  - 示例：https://antfu.me/
  - 示例：https://antfu.me/demos
  - ……另有 7 个

### ⚪ 提示（3 处，1 类）

- **soft404** — 疑似软 404（需确认） · 影响 3 个页面
  - 示例：https://antfu.me/photos
  - 示例：https://antfu.me/projects
  - 示例：https://antfu.me/sponsors-list
