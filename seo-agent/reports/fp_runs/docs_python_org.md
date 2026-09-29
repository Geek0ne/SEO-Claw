# SEO 体检报告 · docs.python.org

扫描时间：2026-09-29 11:56 UTC · 耗时 11s · 抓取 5 / 发现 431 个 URL

## 健康分：88 / 100

共 12 个问题：🔴 严重 0 · 🟠 高 2 · 🟡 中 5 · 🔵 低 5

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 96 |
| 信息架构 | 100 |
| 页面内容质量 | 93 |
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

### 2. [中] canonical 指向了其他页面（需确认是否有意为之）

canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。这可能是有意为之（内容已合并、历史版本别名、分页主页面），也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。

**怎么修**：逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。

**证据**：

- **verdict**: possibly_intentional
- `canonical_target_status` = `None`
- `canonical` = `https://docs.python.org/3/index.html`
- `page_url` = `https://docs.python.org/3.10/`

### 3. [中] 多个页面 meta description 相同

相同的 description 让这些页面在搜索结果里长得一样，用户没有理由点开第二个。

**怎么修**：每页 description 描述该页面独有的内容与卖点。

**证据**：

- https://docs.python.org/
- https://docs.python.org/3.12/
- https://docs.python.org/3.13/

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

## 全部问题明细

### 🟠 高（2 处，1 类）

- **meta.missing** — 页面缺少 meta description · 影响 2 个页面
  - **根因推测**：索引信号缺失
  - 搜索引擎拿不到该收录什么页面的明确信号。
  - 示例：https://docs.python.org/3.10/
  - 示例：https://docs.python.org/3.11/

### 🟡 中（5 处，2 类）

- **canonical.conflict** — canonical 指向了其他页面（需确认是否有意为之） · 影响 4 个页面
  - **根因推测**：canonical 指向了其它页面
  - 先确认这是有意的合并/版本别名，还是模板漏改。若是有意的，保持现状即可。
  - 示例：https://docs.python.org/3.10/
  - 示例：https://docs.python.org/3.11/
  - 示例：https://docs.python.org/3.12/
  - ……另有 1 个
- **meta.duplicate** — 多个页面 meta description 相同 · 全站

### 🔵 低（5 处，1 类）

- **schema.missing** — 页面没有结构化数据 · 影响 5 个页面
  - 示例：https://docs.python.org/
  - 示例：https://docs.python.org/3.10/
  - 示例：https://docs.python.org/3.11/
  - ……另有 2 个
