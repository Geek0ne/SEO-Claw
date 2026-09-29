# SEO 体检报告 · antfu.me

扫描时间：2026-09-29 05:30 UTC · 耗时 90s · 抓取 25 / 发现 221 个 URL

## 健康分：73 / 100

共 114 个问题：🔴 严重 0 · 🟠 高 32 · 🟡 中 31 · 🔵 低 48

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 95 |
| 信息架构 | 100 |
| 页面内容质量 | 79 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 99 |

## 最该先做的 5 件事

### 1. [高] 页面缺少 meta description

description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。

**怎么修**：补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。

```html
<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">
```

**证据**：

- `meta_description_found` = `False`

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

### 4. [高] 站点没有可用的 sitemap

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

### 5. [高] 多个页面 title 完全相同

重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。

**怎么修**：为每个页面写能体现其独特价值的 title，用页面主题词区分。

**证据**：

- https://antfu.me/
- https://antfu.me/posts
- https://antfu.me/projects
- ……另有 7 个

## 全部问题明细

### 🟠 高（32）

- **h1.missing** — 页面没有 H1 标题 · `https://100.antfu.me/`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://antfu.me/notes`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://antfu.me/photos`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://antfu.me/podcasts`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://antfu.me/posts`
  - h1_count: `0`

- **h1.missing** — 页面没有 H1 标题 · `https://antfu.me/streams`
  - h1_count: `0`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://antfu.me/demos`
  - page_url: `https://antfu.me/demos`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/demos`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/notes`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/photos`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/podcasts`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/async-sync-in-between`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/categorize-deps`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/ecosystem-sponsorship-forwarding`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/epoch-semver`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/hello-tokyo`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/mental-health-oss`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/mental-health-oss-zh`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/move-on-to-esm-only`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/ohayo-tokyo`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/photos-page`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/pluggable-extensible-playful-devtools`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/posts/sponsorship-forwarding`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/projects`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/sponsors-list`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/streams`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/talks`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://antfu.me/use`
  - meta_description_found: `False`

- **sitemap.missing** — 站点没有可用的 sitemap · 全站
  - tried_paths: `[]`
  - error: `None`

- **title.duplicate** — 多个页面 title 完全相同 · 全站
  - 示例：https://antfu.me/
  - 示例：https://antfu.me/posts
  - 示例：https://antfu.me/projects

### 🟡 中（31）

- **canonical.missing** — 页面缺少 canonical 标签 · `https://100.antfu.me/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/demos`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/notes`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/photos`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/podcasts`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/async-sync-in-between`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/categorize-deps`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/ecosystem-sponsorship-forwarding`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/epoch-semver`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/hello-tokyo`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/mental-health-oss`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/mental-health-oss-zh`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/move-on-to-esm-only`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/ohayo-tokyo`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/photos-page`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/pluggable-extensible-playful-devtools`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/posts/sponsorship-forwarding`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/projects`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/sponsors-list`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/streams`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/talks`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://antfu.me/use`
  - canonical_found: `False`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/photos`
  - missing_count: `570`
  - total_images: `579`
  - sample_srcs: `['https://antfu.me/assets/p-2026-07-11-05-07-19-000-1-BWY0eLxJ.jpg', 'https://antfu.me/assets/p-2026-07-11-04-56-41-000-1-EkQHsgE2.jpg', 'https://antfu.me/as...`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/hello-tokyo`
  - missing_count: `12`
  - total_images: `17`
  - sample_srcs: `['https://antfu.me/assets/p-2025-03-18-23-32-18-000-1-DLG86UdC.jpg', 'https://antfu.me/assets/p-2025-03-18-23-38-45-000-1-qMDtd6dP.jpg', 'https://antfu.me/as...`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/mental-health-oss`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://antfu.me/images/oss-mental-iron-triangle.svg']`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/mental-health-oss-zh`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://antfu.me/images/oss-mental-iron-triangle-zh.svg']`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/move-on-to-esm-only`
  - missing_count: `4`
  - total_images: `4`
  - sample_srcs: `['https://antfu.me/images/npm-esm-vs-cjs-2024.svg', 'https://antfu.me/images/node-modules-inspector-1.png', 'https://antfu.me/images/node-modules-inspector-2...`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/ohayo-tokyo`
  - missing_count: `12`
  - total_images: `17`
  - sample_srcs: `['https://antfu.me/assets/p-2025-03-18-23-32-18-000-1-DLG86UdC.jpg', 'https://antfu.me/assets/p-2025-03-18-23-38-45-000-1-qMDtd6dP.jpg', 'https://antfu.me/as...`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://antfu.me/posts/photos-page`
  - missing_count: `12`
  - total_images: `12`
  - sample_srcs: `['https://antfu.me/assets/p-2026-07-11-05-07-19-000-1-BWY0eLxJ.jpg', 'https://antfu.me/assets/p-2026-07-11-04-56-41-000-1-EkQHsgE2.jpg', 'https://antfu.me/as...`

- **soft404** — 疑似软 404（需确认） · `https://100.antfu.me/`
  - **verdict**: uncertain
  - **verdict_explain**: 信号不明确，请人工看一眼
  - internal_outbound_links: `0`
  - inbound_links: `8`
  - url_looks_like_index: `False`
  - word_count: `8`
  - text_preview: `100 days`
  - status_code: `200`


### 🔵 低（48）

- **schema.missing** — 页面没有结构化数据 · `https://100.antfu.me/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/demos`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/notes`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/photos`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/podcasts`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/async-sync-in-between`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/categorize-deps`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/ecosystem-sponsorship-forwarding`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/epoch-semver`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/hello-tokyo`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/mental-health-oss`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/mental-health-oss-zh`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/move-on-to-esm-only`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/ohayo-tokyo`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/photos-page`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/pluggable-extensible-playful-devtools`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/posts/sponsorship-forwarding`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/projects`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/sponsors-list`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/streams`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/talks`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://antfu.me/use`
  - jsonld_count: `0`
  - microdata_count: `0`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://100.antfu.me/`
  - title: `100 days`
  - length: `8`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/demos`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/notes`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/photos`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/podcasts`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/async-sync-in-between`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/categorize-deps`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/ecosystem-sponsorship-forwarding`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/epoch-semver`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/hello-tokyo`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/mental-health-oss`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/mental-health-oss-zh`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/move-on-to-esm-only`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/ohayo-tokyo`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/photos-page`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/pluggable-extensible-playful-devtools`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/posts/sponsorship-forwarding`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/projects`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/sponsors-list`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/streams`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/talks`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://antfu.me/use`
  - title: `Anthony Fu`
  - length: `10`
  - min: `15`


### ⚪ 提示（3）

- **soft404** — 疑似软 404（需确认） · `https://antfu.me/photos`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `10`
  - inbound_links: `52`
  - url_looks_like_index: `False`
  - word_count: `79`
  - text_preview: `Thank you for being interested in my photos. You can find the tools I use here.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://antfu.me/projects`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `18`
  - inbound_links: `50`
  - url_looks_like_index: `False`
  - word_count: `233`
  - text_preview: `Projects that I created or maintaining. If you enjoy my work and find them useful, consider sponsor me and the ecosystem`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://antfu.me/sponsors-list`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `10`
  - inbound_links: `44`
  - url_looks_like_index: `False`
  - word_count: `43`
  - text_preview: `Sponsors Great thanks for all the Sponsors!`
  - status_code: `200`

