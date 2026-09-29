# SEO 体检报告 · danluu.com

扫描时间：2026-09-29 11:56 UTC · 耗时 7s · 抓取 5 / 发现 357 个 URL

## 健康分：59 / 100

共 21 个问题：🔴 严重 1 · 🟠 高 10 · 🟡 中 4 · 🔵 低 6

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 90 |
| 信息架构 | 100 |
| 页面内容质量 | 70 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [高] 页面没有 H1 标题

H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。

**怎么修**：加一个 H1 写清页面主标题，位置放在正文开头。

**证据**：

- `h1_count` = `0`

### 2. [高] 页面缺少 meta description

description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。

**怎么修**：补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。

```html
<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">
```

**证据**：

- `meta_description_found` = `False`

### 3. [严重] 页面缺少 title 标签

title 是搜索结果里最重要的可点击文案。缺失时搜索引擎会自行从页面内容里截取，排名与点击率都会受损。

**怎么修**：在 <head> 里加一个 <title>，写成「核心关键词 - 品牌名」的结构。

```html
<head>
  <title>防水登山鞋 男款防滑 - 品牌名</title>
</head>
```

**证据**：

- `html_title_found` = `False`

### 4. [中] 页面缺少 canonical 标签

URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。

**怎么修**：在 <head> 里加 <link rel="canonical" href="本页的规范地址">。

```html
<link rel="canonical" href="https://example.com/product/123">
```

**证据**：

- `canonical_found` = `False`

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

### 🔴 严重（1 处，1 类）

- **title.missing** — 页面缺少 title 标签 · `https://danluu.com/`
  - 示例：https://danluu.com/

### 🟠 高（10 处，2 类）

- **h1.missing** — 页面没有 H1 标题 · 影响 5 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://danluu.com/
  - 示例：https://danluu.com/agentic-testing/
  - 示例：https://danluu.com/brain-off/
  - ……另有 2 个
- **meta.missing** — 页面缺少 meta description · 影响 5 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://danluu.com/
  - 示例：https://danluu.com/agentic-testing/
  - 示例：https://danluu.com/brain-off/
  - ……另有 2 个

### 🟡 中（4 处，1 类）

- **canonical.missing** — 页面缺少 canonical 标签 · 影响 4 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://danluu.com/agentic-testing/
  - 示例：https://danluu.com/brain-off/
  - 示例：https://danluu.com/bug-blind/
  - ……另有 1 个

### 🔵 低（6 处，2 类）

- **schema.missing** — 页面没有结构化数据 · 影响 5 个页面
  - 示例：https://danluu.com/
  - 示例：https://danluu.com/agentic-testing/
  - 示例：https://danluu.com/brain-off/
  - ……另有 2 个
- **title.too_short** — title 过短，浪费了黄金位置 · `https://danluu.com/bug-blind/`
  - **根因推测**：多个页面共用同一套 title
  - 这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，而不是把 title 加长到不报“过短”为止。
  - 示例：https://danluu.com/bug-blind/
