# SEO 体检报告 · jvns.ca

扫描时间：2026-09-29 08:35 UTC · 耗时 7s · 抓取 8 / 发现 2200 个 URL

## 健康分：95 / 100

共 18 个问题：🔴 严重 0 · 🟠 高 0 · 🟡 中 5 · 🔵 低 13

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 99 |
| 信息架构 | 100 |
| 页面内容质量 | 97 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [中] 页面有多个 H1

多个 H1 会让主题信号分散。HTML5 允许多个 H1，但实践中一个主 H1 对 SEO 更稳妥。

**怎么修**：保留一个主 H1，其余同级标题降为 H2。

**证据**：

- `h1_count` = `2`
- `h1_list` = `['Julia Evans', 'Learning a few things about running SQLite']`

### 2. [低] 页面没有结构化数据

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

### 3. [中] canonical 指向了其他页面（需确认是否有意为之）

canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。这可能是有意为之（内容已合并、历史版本别名、分页主页面），也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。

**怎么修**：逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。

**证据**：

- **verdict**: possibly_intentional
- `canonical_target_status` = `None`
- `canonical` = `https://jvns.ca/juliasections/Uncategorized/`
- `page_url` = `https://jvns.ca/juliasections/uncategorized/`

### 4. [中] 图片缺少 alt 文本

alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。

**怎么修**：补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。

```html
<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">
```

**证据**：

- `missing_count` = `4`
- `total_images` = `4`
- `sample_srcs` = `['https://jvns.ca/images/pcb.png', 'https://jvns.ca/images/battery.png', 'https://jvns.ca/images/light-after-1.png', 'https://jvns.ca/images/light-after-2.png']`

### 5. [低] title 过短，浪费了黄金位置

过短的 title 通常意味着没覆盖到用户搜索的关键词，浪费了搜索结果里最显眼的位置。

**怎么修**：补充用户真实会用到的搜索词，保持自然可读。

**证据**：

- `title` = `Julia Evans`
- `length` = `11`
- `min` = `15`

## 全部问题明细

### 🟡 中（5 处，3 类）

- **h1.multiple** — 页面有多个 H1 · 影响 3 个页面
  - 示例：https://jvns.ca/blog/2026/07/17/learning-about-running-sqlite/
  - 示例：https://jvns.ca/blog/2026/07/21/more-nice-django-things/
  - 示例：https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/
- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://jvns.ca/juliasections/Uncategorized/`
  - **根因推测**：canonical 指向了其它页面
  - 先确认这是有意的合并/版本别名，还是模板漏改。若是有意的，保持现状即可。
  - 示例：https://jvns.ca/juliasections/Uncategorized/
- **img.alt.missing** — 图片缺少 alt 文本 · `https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/`
  - 示例：https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/

### 🔵 低（13 处，2 类）

- **schema.missing** — 页面没有结构化数据 · 影响 8 个页面
  - 示例：https://jvns.ca/
  - 示例：https://jvns.ca/blog/2026/07/17/learning-about-running-sqlite/
  - 示例：https://jvns.ca/blog/2026/07/21/more-nice-django-things/
  - ……另有 5 个
- **title.too_short** — title 过短，浪费了黄金位置 · 影响 5 个页面
  - **根因推测**：多个页面共用同一套 title
  - 这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，而不是把 title 加长到不报“过短”为止。
  - 示例：https://jvns.ca/
  - 示例：https://jvns.ca/categories/
  - 示例：https://jvns.ca/juliasections/
  - ……另有 2 个
