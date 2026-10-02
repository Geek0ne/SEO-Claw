# SEO 体检报告 · docs.python.org

扫描时间：2026-09-29 00:08 UTC · 耗时 41s · 抓取 40 / 发现 7126 个 URL

## 健康分：73 / 100

共 136 个问题：🔴 严重 0 · 🟠 高 54 · 🟡 中 43 · 🔵 低 39

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 91 |
| 信息架构 | 96 |
| 页面内容质量 | 92 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 95 |

## 最该先做的 5 件事

### 1. [高] canonical 指向了其他页面

canonical 指向的 URL 与当前页面不一致时，搜索引擎会把本页权重全部转移给目标页。如果是你有意的（内容已合并）就没问题，但多数情况是复制模板时漏改的。

**怎么修**：确认是否真的要把权重转移出去；不是的话改成指向本页自身。

**证据**：

- `canonical` = `https://docs.python.org/2/index.html`
- `page_url` = `https://docs.python.org/2.7/`

### 2. [高] 页面缺少 meta description

description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。

**怎么修**：补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。

```html
<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">
```

**证据**：

- `meta_description_found` = `False`

### 3. [高] HTTPS 页面存在混合内容

HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。

**怎么修**：把所有 http:// 资源改成 https://，或用协议相对路径。

```html
把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">
```

**证据**：

- `page_url` = `https://docs.python.org/2.6/`

### 4. [中] 内部链接锚文本为空

空锚文本（如 `<a href="/x"></a>`）对用户和搜索引擎都没有传递任何信息，也会带来可访问性问题。

**怎么修**：给链接加上描述性锚文本。

**证据**：

- `empty_anchor_count` = `1`
- `sample_hrefs` = `['https://www.python.org/']`

### 5. [高] 多个页面 title 完全相同

重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。

**怎么修**：为每个页面写能体现其独特价值的 title，用页面主题词区分。

**证据**：

- https://docs.python.org/3
- https://docs.python.org/3.14/

## 全部问题明细

### 🟠 高（54）

- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/2.7/`
  - canonical: `https://docs.python.org/2/index.html`
  - page_url: `https://docs.python.org/2.7/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.0/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.0/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.1/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.1/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.10/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.10/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.11/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.11/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.12/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.12/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.13/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.13/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.14/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.14/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.15/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.15/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.16/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.16/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.2/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.2/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.3/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.3/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.4/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.4/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.5/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.5/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.6/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.6/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.7/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.7/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.8/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.8/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://docs.python.org/3.9/`
  - canonical: `https://docs.python.org/3/index.html`
  - page_url: `https://docs.python.org/3.9/`
- **canonical.conflict** — canonical 指向了其他页面 · `https://peps.python.org/`
  - canonical: `https://peps.python.org/pep-0000/`
  - page_url: `https://peps.python.org/`
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
- **soft404** — 疑似软 404 · `https://docs.python.org/3/genindex.html`
  - word_count: `28`
  - text_preview: `Index Index pages by letter:`
  - status_code: `200`
- **soft404** — 疑似软 404 · `https://docs.python.org/3/using/index.html`
  - word_count: `210`
  - text_preview: `This part of the documentation is devoted to general information on the setup of the Python environment on different pla`
  - status_code: `200`
- **title.duplicate** — 多个页面 title 完全相同 · 全站
  - 示例：https://docs.python.org/3
  - 示例：https://docs.python.org/3.14/

### 🟡 中（43）

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
  - h1_list: `['Intuitive Interpretation', 'Compound Data Types', 'All the Flow You’d Expect', 'Functions Defined', 'Quick & Easy t...`
- **h1.multiple** — 页面有多个 H1 · `https://www.python.org/doc/av/`
  - h1_count: `4`
  - h1_list: `['Audio/Video Instructional Materials for Python', 'Podcast Repositories', 'Inactive Podcast Repositories', 'Conferen...`
- **img.alt.missing** — 图片缺少 alt 文本 · `https://wiki.python.org/moin/BeginnersGuide`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://wiki.python.org/moin/logo.png']`
- **img.alt.missing** — 图片缺少 alt 文本 · `https://wiki.python.org/moin/PythonBooks`
  - missing_count: `1`
  - total_images: `1`
  - sample_srcs: `['https://wiki.python.org/moin/logo.png']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.10/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.11/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.12/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.13/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.14/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.15/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.16/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.8/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3.9/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/builtins/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/download.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/extending/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/genindex.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/howto/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/installing/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/library/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/py-modindex.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/reference/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/tutorial/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/using/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/whatsnew/3.14.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://docs.python.org/3/whatsnew/index.html`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://wiki.python.org/moin/BeginnersGuide`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://wiki.python.org/moin/FrontPage.html']`
- **link.noanchor** — 内部链接锚文本为空 · `https://wiki.python.org/moin/PythonBooks`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://wiki.python.org/moin/FrontPage.html']`
- **link.noanchor** — 内部链接锚文本为空 · `https://www.python.org/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://www.python.org/doc/av/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **link.noanchor** — 内部链接锚文本为空 · `https://www.python.org/doc/versions/`
  - empty_anchor_count: `1`
  - sample_hrefs: `['https://www.python.org/']`
- **meta.duplicate** — 多个页面 meta description 相同 · 全站
  - 示例：https://docs.python.org/3
  - 示例：https://docs.python.org/3.12/
  - 示例：https://docs.python.org/3.13/
- **title.too_long** — title 过长会被截断 · `https://docs.python.org/3/extending/index.html`
  - title: `Extending and Embedding the Python Interpreter — Python 3.14.7 documentation`
  - length: `76`
  - limit: `60`
- **title.too_long** — title 过长会被截断 · `https://peps.python.org/`
  - title: `PEP 0 – Index of Python Enhancement Proposals (PEPs) | peps.python.org`
  - length: `70`
  - limit: `60`

### 🔵 低（39）

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
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/builtins/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/download.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/extending/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/genindex.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/howto/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/installing/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/library/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/py-modindex.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/reference/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/tutorial/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/using/index.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/whatsnew/3.14.html`
  - jsonld_count: `0`
  - microdata_count: `0`
- **schema.missing** — 页面没有结构化数据 · `https://docs.python.org/3/whatsnew/index.html`
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
