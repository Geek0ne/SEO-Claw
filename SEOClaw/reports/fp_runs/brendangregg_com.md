# SEO 体检报告 · brendangregg.com

扫描时间：2026-09-29 11:56 UTC · 耗时 12s · 抓取 5 / 发现 1114 个 URL

## 健康分：76 / 100

共 23 个问题：🔴 严重 0 · 🟠 高 3 · 🟡 中 14 · 🔵 低 5

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 96 |
| 信息架构 | 95 |
| 页面内容质量 | 89 |
| 性能与体验 | 100 |
| 结构化数据 | 99 |
| 安全与信任 | 97 |

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

### 2. [中] 图片缺少 alt 文本

alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。

**怎么修**：补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。

```html
<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">
```

**证据**：

- `missing_count` = `5`
- `total_images` = `5`
- `sample_srcs` = `['https://www.brendangregg.com/Images/sysperf2nd_bookcover_360.jpg', 'https://www.brendangregg.com/Images/bpfperftools_bookcover_360.jpg', 'https://www.brendangregg.com/Images/brendan_rajasthan2011...`

### 3. [中] 内部链接锚文本为空

空锚文本（如 `<a href="/x"></a>`）对用户和搜索引擎都没有传递任何信息，也会带来可访问性问题。

**怎么修**：给链接加上描述性锚文本。

**证据**：

- `empty_anchor_count` = `5`
- `sample_hrefs` = `['https://www.brendangregg.com/systems-performance-2nd-edition-book.html', 'https://www.brendangregg.com/bpf-performance-tools-book.html', 'https://www.brendangregg.com/appearance.html', 'https://w...`

### 4. [中] 页面缺少 canonical 标签

URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。

**怎么修**：在 <head> 里加 <link rel="canonical" href="本页的规范地址">。

```html
<link rel="canonical" href="https://example.com/product/123">
```

**证据**：

- `canonical_found` = `False`

### 5. [高] HTTPS 页面存在混合内容

HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。

**怎么修**：把所有 http:// 资源改成 https://，或用协议相对路径。

```html
把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">
```

**证据**：

- `page_url` = `https://www.brendangregg.com/overview.html`
- `offending_resources` = `['<img src=http://www.assoc-amazon.com/e/ir?t=deirdrestraug-20&l=as2&o=1&a=0133390098>', '<img src=http://www.assoc-amazon.com/e/ir?t=deirdrestraug-20&l=as2&o=1&a=0132091518>', '<img src=http://www...`
- `note` = `只统计 img/script/link/iframe 等子资源，不含 <a href> 超链接`

## 全部问题明细

### 🟠 高（3 处，3 类）

- **http.mixed_content** — HTTPS 页面存在混合内容 · `https://www.brendangregg.com/overview.html`
  - 示例：https://www.brendangregg.com/overview.html
- **meta.missing** — 页面缺少 meta description · `https://www.brendangregg.com/overview.html`
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://www.brendangregg.com/overview.html
- **sitemap.missing** — 站点没有可用的 sitemap · 全站

### 🟡 中（14 处，3 类）

- **img.alt.missing** — 图片缺少 alt 文本 · 影响 5 个页面
  - 示例：https://brendangregg.com/
  - 示例：https://www.brendangregg.com/blog/index.html
  - 示例：https://www.brendangregg.com/bpf-performance-tools-book.html
  - ……另有 2 个
- **link.noanchor** — 内部链接锚文本为空 · 影响 5 个页面
  - 示例：https://brendangregg.com/
  - 示例：https://www.brendangregg.com/blog/index.html
  - 示例：https://www.brendangregg.com/bpf-performance-tools-book.html
  - ……另有 2 个
- **canonical.missing** — 页面缺少 canonical 标签 · 影响 4 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://www.brendangregg.com/blog/index.html
  - 示例：https://www.brendangregg.com/bpf-performance-tools-book.html
  - 示例：https://www.brendangregg.com/overview.html
  - ……另有 1 个

### 🔵 低（5 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 5 个页面
  - 示例：https://brendangregg.com/
  - 示例：https://www.brendangregg.com/blog/index.html
  - 示例：https://www.brendangregg.com/bpf-performance-tools-book.html
  - ……另有 2 个

### ⚪ 提示（1 处，1 类）

- **h1.multiple** — 页面有多个 H1（Google 不惩罚，仅供参考） · `https://www.brendangregg.com/blog/index.html`
  - 示例：https://www.brendangregg.com/blog/index.html
