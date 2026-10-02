# SEO 体检报告 · docs.python.org

扫描时间：2026-09-29 05:25 UTC · 耗时 43s · 抓取 30 / 发现 4685 个 URL

## 健康分：77 / 100

共 96 个问题：🔴 严重 0 · 🟠 高 33 · 🟡 中 33 · 🔵 低 29

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 96 |
| 信息架构 | 100 |
| 页面内容质量 | 89 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 94 |

## 最该先做的 5 件事

### 1. [高] 页面缺少 meta description

description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。

**怎么修**：补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。

```html
<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">
```

**证据**：

- `meta_description_found` = `False`

### 2. [高] HTTPS 页面存在混合内容

HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。

**怎么修**：把所有 http:// 资源改成 https://，或用协议相对路径。

```html
把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">
```

**证据**：

- `page_url` = `https://docs.python.org/2.6/`

### 3. [中] canonical 指向了其他页面（需确认是否有意为之）

canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。这可能是有意为之（内容已合并、历史版本别名、分页主页面），也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。

**怎么修**：逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。

**证据**：

- **verdict**: possibly_intentional
- `canonical_target_status` = `200`
- `canonical` = `https://docs.python.org/2/index.html`
- `page_url` = `https://docs.python.org/2.7/`

### 4. [高] 多个页面 title 完全相同

重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。

**怎么修**：为每个页面写能体现其独特价值的 title，用页面主题词区分。

**证据**：

- https://docs.python.org/3
- https://docs.python.org/3.14/

### 5. [中] 页面缺少 canonical 标签

URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。

**怎么修**：在 <head> 里加 <link rel="canonical" href="本页的规范地址">。

```html
<link rel="canonical" href="https://example.com/product/123">
```

**证据**：

- `canonical_found` = `False`

## 全部问题明细

### 🟠 高（33）

- **h1.missing** — 页面没有 H1 标题 · `https://wiki.python.org/moin/PythonBooks`
  - h1_count: `0`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/2.6/`
  - page_url: `https://docs.python.org/2.6/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/2.7/`
  - page_url: `https://docs.python.org/2.7/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.0/`
  - page_url: `https://docs.python.org/3.0/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.1/`
  - page_url: `https://docs.python.org/3.1/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.2/`
  - page_url: `https://docs.python.org/3.2/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.3/`
  - page_url: `https://docs.python.org/3.3/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.4/`
  - page_url: `https://docs.python.org/3.4/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.5/`
  - page_url: `https://docs.python.org/3.5/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.6/`
  - page_url: `https://docs.python.org/3.6/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://docs.python.org/3.7/`
  - page_url: `https://docs.python.org/3.7/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://wiki.python.org/moin/BeginnersGuide`
  - page_url: `https://wiki.python.org/moin/BeginnersGuide`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://www.python.org/`
  - page_url: `https://www.python.org/`

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://www.python.org/doc/av/`
  - page_url: `https://www.python.org/doc/av/`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/2.6/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/2.7/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.0/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.1/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.10/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.11/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.2/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.3/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.4/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.5/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.6/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.7/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.8/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3.9/`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3/genindex.html`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://docs.python.org/3/py-modindex.html`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://wiki.python.org/moin/BeginnersGuide`
  - meta_description_found: `False`

- **meta.missing** — 页面缺少 meta description · `https://wiki.python.org/moin/PythonBooks`
  - meta_description_found: `False`

- **title.duplicate** — 多个页面 title 完全相同 · 全站
  - 示例：https://docs.python.org/3
  - 示例：https://docs.python.org/3.14/

### 🟡 中（33）

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/2.7/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/2/index.html`
  - page_url: `https://docs.python.org/2.7/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.0/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.0/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.1/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.1/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.10/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.10/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.11/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.11/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.12/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.12/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.13/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.13/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.14/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.14/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.15/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.15/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.16/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.16/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.2/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.2/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.3/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.3/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.4/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.4/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.5/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.5/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.6/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.6/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.7/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.7/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.8/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.8/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://docs.python.org/3.9/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.9/`

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · `https://peps.python.org/`
  - **verdict**: possibly_intentional
  - canonical_target_status: `200`
  - canonical: `https://peps.python.org/pep-0000/`
  - page_url: `https://peps.python.org/`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://devguide.python.org/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://docs.python.org/2.6/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://wiki.python.org/moin/BeginnersGuide`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://wiki.python.org/moin/PythonBooks`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://www.python.org/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://www.python.org/doc/av/`
  - canonical_found: `False`

- **canonical.missing** — 页面缺少 canonical 标签 · `https://www.python.org/doc/versions/`
  - canonical_found: `False`

- **h1.multiple** — 页面有多个 H1 · `https://peps.python.org/`
  - h1_count: `2`
  - h1_list: `['Python Enhancement Proposals', 'PEP 0 – Index of Python Enhancement Proposals (PEPs)']`

- **h1.multiple** — 页面有多个 H1 · `https://www.python.org/`
  - h1_count: `5`
  - h1_list: `['Intuitive Interpretation', 'Compound Data Types', 'All the Flow You’d Expect', 'Functions Defined', 'Quick & Easy to Learn']`

- **h1.multiple** — 页面有多个 H1 · `https://www.python.org/doc/av/`
  - h1_count: `4`
  - h1_list: `['Audio/Video Instructional Materials for Python', 'Podcast Repositories', 'Inactive Podcast Repositories', 'Conference Talk and Video Lecture Repositories']`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://wiki.python.org/moin/BeginnersGuide`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://wiki.python.org/moin/logo.png']`

- **img.alt.missing** — 图片缺少 alt 文本 · `https://wiki.python.org/moin/PythonBooks`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://wiki.python.org/moin/logo.png']`

- **meta.duplicate** — 多个页面 meta description 相同 · 全站
  - 示例：https://docs.python.org/3
  - 示例：https://docs.python.org/3.12/
  - 示例：https://docs.python.org/3.13/
- **title.too_long** — title 过长会被截断 · `https://peps.python.org/`
  - title: `PEP 0 – Index of Python Enhancement Proposals (PEPs) | peps.python.org`
  - length: `70`
  - limit: `60`


### 🔵 低（29）

- **schema.missing** — 页面没有结构化数据 · `https://devguide.python.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/2.6/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/2.7/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.0/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.1/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.10/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.11/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.12/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.13/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.14/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.15/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.16/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.2/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.3/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.4/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.5/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.6/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.7/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.8/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3.9/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/download.html`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/genindex.html`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/py-modindex.html`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://peps.python.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://wiki.python.org/moin/BeginnersGuide`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://wiki.python.org/moin/PythonBooks`
  - jsonld_count: `0`
  - microdata_count: `0`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://wiki.python.org/moin/BeginnersGuide`
  - title: `BeginnersGuide`
  - length: `14`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://wiki.python.org/moin/PythonBooks`
  - title: `PythonBooks`
  - length: `11`
  - min: `15`


### ⚪ 提示（1）

- **soft404** — 疑似软 404（需确认） · `https://docs.python.org/3/genindex.html`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `40`
  - inbound_links: `14`
  - url_looks_like_index: `True`
  - word_count: `28`
  - text_preview: `Index Index pages by letter:`
  - status_code: `200`

