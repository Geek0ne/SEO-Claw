# SEO 体检报告 · developer.mozilla.org

扫描时间：2026-09-29 05:33 UTC · 耗时 9s · 抓取 10 / 发现 21374 个 URL

## 健康分：92 / 100

共 20 个问题：🔴 严重 1 · 🟠 高 2 · 🟡 中 2 · 🔵 低 14

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 97 |
| 信息架构 | 100 |
| 页面内容质量 | 98 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 98 |

## 最该先做的 5 件事

### 1. [高] 多个页面 title 完全相同

重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。

**怎么修**：为每个页面写能体现其独特价值的 title，用页面主题词区分。

**证据**：

- https://developer.mozilla.org/
- https://developer.mozilla.org/en-US/

### 2. [严重] 页面被 noindex 屏蔽收录

noindex 会让页面完全不出现在搜索结果里。这通常是开发环境忘记删，或者模板改版时误加。

**怎么修**：如果页面应该被收录，删掉 noindex；如果是故意屏蔽（如分页页），请在 sitemap 中也排除它。

**证据**：

- `robots_meta` = `noindex, nofollow`

### 3. [中] 多个页面 meta description 相同

相同的 description 让这些页面在搜索结果里长得一样，用户没有理由点开第二个。

**怎么修**：每页 description 描述该页面独有的内容与卖点。

**证据**：

- https://developer.mozilla.org/en-US/
- https://developer.mozilla.org/en-US/404
- https://developer.mozilla.org/en-US/about
- ……另有 2 个

### 4. [高] HTTPS 页面存在混合内容

HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。

**怎么修**：把所有 http:// 资源改成 https://，或用协议相对路径。

```html
把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">
```

**证据**：

- `page_url` = `https://developer.mozilla.org/en-US/about`

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

### 🔴 严重（1）

- **noindex.present** — 页面被 noindex 屏蔽收录 · `https://developer.mozilla.org/en-US/404`
  - robots_meta: `noindex, nofollow`


### 🟠 高（2）

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://developer.mozilla.org/en-US/about`
  - page_url: `https://developer.mozilla.org/en-US/about`

- **title.duplicate** — 多个页面 title 完全相同 · 全站
  - 示例：https://developer.mozilla.org/
  - 示例：https://developer.mozilla.org/en-US/

### 🟡 中（2）

- **link.noanchor** — 内部链接锚文本为空 · `https://developer.mozilla.org/en-US/blog/`
  - empty_anchor_count: `4`
  - sample_hrefs: `['https://developer.mozilla.org/en-US/blog/view-transitions-beginner-guide/', 'https://developer.mozilla.org/en-US/blog/introducing-the-mdn-playground/', 'ht...`

- **meta.duplicate** — 多个页面 meta description 相同 · 全站
  - 示例：https://developer.mozilla.org/en-US/
  - 示例：https://developer.mozilla.org/en-US/404
  - 示例：https://developer.mozilla.org/en-US/about

### 🔵 低（14）

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/404`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/about`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/advertising`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/blog/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/blog/accessibility-celebrating-gaad-2023/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/blog/ai-explain-postmortem/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/blog/announcing-mdn-front-end-developer-curriculum/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **schema.missing** — 页面没有结构化数据 · `https://developer.mozilla.org/en-US/blog/aria-accessibility-html-landmark-roles/`
  - jsonld_count: `0`
  - microdata_count: `0`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://developer.mozilla.org/`
  - title: `MDN Web Docs`
  - length: `12`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://developer.mozilla.org/en-US/`
  - title: `MDN Web Docs`
  - length: `12`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://developer.mozilla.org/en-US/about`
  - title: `About MDN`
  - length: `9`
  - min: `15`

- **title.too_short** — title 过短，浪费了黄金位置 · `https://developer.mozilla.org/en-US/blog/`
  - title: `MDN Blog`
  - length: `8`
  - min: `15`


### ⚪ 提示（1）

- **soft404** — 疑似软 404（需确认） · `https://developer.mozilla.org/en-US/404`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `110`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `96`
  - text_preview: `Page not found | MDN Skip to main content Skip to search Page not found Go back to the home page`
  - status_code: `200`

