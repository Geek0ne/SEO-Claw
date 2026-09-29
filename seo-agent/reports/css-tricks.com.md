# SEO 体检报告 · css-tricks.com

扫描时间：2026-09-29 05:35 UTC · 耗时 172s · 抓取 25 / 发现 20681 个 URL

## 健康分：98 / 100

共 18 个问题：🔴 严重 1 · 🟠 高 0 · 🟡 中 5 · 🔵 低 0

| 维度 | 得分 |
|---|---|
| 可抓取与收录 | 99 |
| 信息架构 | 100 |
| 页面内容质量 | 99 |
| 性能与体验 | 100 |
| 结构化数据 | 100 |
| 安全与信任 | 100 |

## 最该先做的 5 件事

### 1. [严重] 页面被 noindex 屏蔽收录

noindex 会让页面完全不出现在搜索结果里。这通常是开发环境忘记删，或者模板改版时误加。

**怎么修**：如果页面应该被收录，删掉 noindex；如果是故意屏蔽（如分页页），请在 sitemap 中也排除它。

**证据**：

- `robots_meta` = `noindex,nofollow`

### 2. [中] title 过长会被截断

title 超出显示长度时会被搜索结果截断，关键信息放不进去就白写了。中文建议 ≤30 字，英文建议 ≤60 字符。

**怎么修**：把最重要的关键词前置，删掉形容词和冗余修饰。

**证据**：

- `title` = `Creating Web Widgets Using the Document Picture-in-Picture API | CSS-Tricks`
- `length` = `75`
- `limit` = `60`

### 3. [提示] 疑似软 404（需确认）

页面返回 200 但正文极少，搜索引擎会识别为软 404 并停止索引。⚠️ 但索引页、目录页、标签页天生内容少，不一定是问题——工具会提供判定信号，请确认：这个页面是“该有内容却没有”，还是“本身就是列表页”。

**怎么修**：如果确实是空页面：返回真正的 404 状态码，或补上内容。如果是索引/列表页：忽略本条即可。

**证据**：

- **verdict**: likely_index_or_hub
- **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
- `internal_outbound_links` = `19`
- `inbound_links` = `0`
- `url_looks_like_index` = `False`
- `word_count` = `62`
- `text_preview` = `Chrome 154 (Dev) trials frame-sizing (for responsive iframes).`
- `status_code` = `200`

## 全部问题明细

### 🔴 严重（1）

- **noindex.present** — 页面被 noindex 屏蔽收录 · `https://css-tricks.com/resolved-css-class-prefix-selector/`
  - robots_meta: `noindex,nofollow`


### 🟡 中（5）

- **title.too_long** — title 过长会被截断 · `https://css-tricks.com/creating-web-widgets-using-the-document-picture-in-picture-api/`
  - title: `Creating Web Widgets Using the Document Picture-in-Picture API | CSS-Tricks`
  - length: `75`
  - limit: `60`

- **title.too_long** — title 过长会被截断 · `https://css-tricks.com/css-random-function-polyfill/`
  - title: `Let’s Use the Emergent CSS random() Function in all the Browsers | CSS-Tricks`
  - length: `77`
  - limit: `60`

- **title.too_long** — title 过长会被截断 · `https://css-tricks.com/how-to-style-the-new-search-text-and-other-highlight-pseudo-elements/`
  - title: `Styling ::search-text and Other Highlight-y Pseudo-Elements | CSS-Tricks`
  - length: `72`
  - limit: `60`

- **title.too_long** — title 过长会被截断 · `https://css-tricks.com/whats-important-17/`
  - title: `What’s !important #17: Custom Highlight API, CSS Navigation Matching, Fixing text-stroke, and More | CSS-Tricks`
  - length: `111`
  - limit: `60`

- **title.too_long** — title 过长会被截断 · `https://css-tricks.com/whats-important-18/`
  - title: `What’s !important #18: <geolocation>, Syntax ::highlight()ing, named-feature(), and More | CSS-Tricks`
  - length: `101`
  - limit: `60`


### ⚪ 提示（12）

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-171/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `19`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `62`
  - text_preview: `Chrome 154 (Dev) trials frame-sizing (for responsive iframes).`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-172/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `25`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `119`
  - text_preview: `Firefox 154 ships sibling-count(), sibling-index(), text-box-trim, text-box-edge, and text-box, which are now Baseline.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-173/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `19`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `141`
  - text_preview: `Chrome 152 ships the autocorrect HTML attribute, making it Baseline, and the alpha() CSS function (Safari and Firefox ar`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-174/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `20`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `111`
  - text_preview: `Safari TP 251 trials corner-shape, object-view-box, at-rule(), ident(), inherit(), random(), and random-item().`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-175/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `22`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `84`
  - text_preview: `Safari TP 251 trials comma-separated @container queries in addition to popover=hint.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-176/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `21`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `98`
  - text_preview: `Firefox 155 ships alpha() and advanced attr(), which Chrome also supports (Safari to follow soon).`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-177/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `20`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `48`
  - text_preview: `Firefox 155 implements progress(), now Baseline.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-178/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `21`
  - inbound_links: `0`
  - url_looks_like_index: `False`
  - word_count: `58`
  - text_preview: `Chrome 155 (Dev) implements margin-trim, following Safari.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-179/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `22`
  - inbound_links: `2`
  - url_looks_like_index: `False`
  - word_count: `98`
  - text_preview: `Chrome 155 (Dev) implements random() (also available in Safari) as well as symbols() (in Firefox).`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-180/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `21`
  - inbound_links: `2`
  - url_looks_like_index: `False`
  - word_count: `87`
  - text_preview: `Chrome 153 becomes the first to implement scroll-axis-lock, <camera>, and <microphone>.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-181/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `19`
  - inbound_links: `2`
  - url_looks_like_index: `False`
  - word_count: `55`
  - text_preview: `Firefox 157 (Nightly) ships overscroll-behavior: chain.`
  - status_code: `200`

- **soft404** — 疑似软 404（需确认） · `https://css-tricks.com/quick-hit-182/`
  - **verdict**: likely_index_or_hub
  - **verdict_explain**: 出链多、URL 形似索引页，大概率是正常的目录/列表页
  - internal_outbound_links: `21`
  - inbound_links: `2`
  - url_looks_like_index: `False`
  - word_count: `53`
  - text_preview: `Safari TP 252 trials named-feature() and user-select.`
  - status_code: `200`

