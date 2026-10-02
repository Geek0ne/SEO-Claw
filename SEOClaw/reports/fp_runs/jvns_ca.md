# SEO 体检报告 · jvns.ca

扫描时间：2026-09-29 11:56 UTC · 耗时 5s · 抓取 5 / 发现 2122 个 URL

## 健康分：97 / 100

共 8 个问题：🔴 严重 0 · 🟠 高 0 · 🟡 中 2 · 🔵 低 5

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 99 |
| 信息架构 | 100 |
| 页面内容质量 | 99 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [中] canonical 指向了其他页面（需确认是否有意为之）

canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。这可能是有意为之（内容已合并、历史版本别名、分页主页面），也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。

**怎么修**：逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。

**证据**：

- **verdict**: possibly_intentional
- `canonical_target_status` = `None`
- `canonical` = `https://jvns.ca/juliasections/Uncategorized/`
- `page_url` = `https://jvns.ca/juliasections/uncategorized/`

### 2. [中] 图片缺少 alt 文本

alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。

**怎么修**：补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。

```html
<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">
```

**证据**：

- `missing_count` = `4`
- `total_images` = `4`
- `sample_srcs` = `['https://jvns.ca/images/pcb.png', 'https://jvns.ca/images/battery.png', 'https://jvns.ca/images/light-after-1.png', 'https://jvns.ca/images/light-after-2.png']`

### 3. [低] 页面没有结构化数据

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

### 4. [提示] 页面有多个 H1（Google 不惩罚，仅供参考）

HTML5 明确允许多个 H1，Google 也公开表示多个 H1 不影响索引或排名。真正会分散主题信号的是「多个 H1 说的是同一件事」——比如站名和文章标题同时进 H1。
⚠️ 所以这条只是提示，不是问题。很多设计良好的站点就是这么做的，不要为了消掉这条去改版面。

**怎么修**：仅当多个 H1 语义重复时才值得处理：保留最具体的一个，其余降为 H2 或改为普通文本。如果站名 H1 是模板刻意为之，保持现状即可。

**证据**：

- **verdict**: likely_intentional
- **verdict_explain**: Google 不惩罚多个 H1，仅供确认主题是否清晰
- `h1_count` = `2`
- `h1_list` = `['Julia Evans', 'Replacing the old battery on rechargeable bike lights']`
- `duplicated` = `False`

## 全部问题明细

### 🟡 中（2 处，2 类）

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://jvns.ca/juliasections/Uncategorized/`
  - **根因推测**：canonical 指向了其它页面
  - 先确认这是有意的合并/版本别名，还是模板漏改。若是有意的，保持现状即可。
  - 示例：https://jvns.ca/juliasections/Uncategorized/
- **img.alt.missing** — 图片缺少 alt 文本 · `https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/`
  - 示例：https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/

### 🔵 低（5 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 5 个页面
  - 示例：https://jvns.ca/
  - 示例：https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/
  - 示例：https://jvns.ca/juliasections/
  - ……另有 2 个

### ⚪ 提示（1 处，1 类）

- **h1.multiple** — 页面有多个 H1（Google 不惩罚，仅供参考） · `https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/`
  - 示例：https://jvns.ca/blog/2026/09/27/replacing-the-old-battery-on-rechargeable-bike-lights/
