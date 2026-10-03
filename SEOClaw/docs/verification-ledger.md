# 回源核对台账（2026-10-04）

184 个站，成功 150 个，报出 483 条问题，涉及 18 条规则。
每条规则抽样本 curl 回原站逐条核对——工具说有问题，页面里到底有没有。

跑法（在 `backend/` 下）：

```bash
python3 ../tools/verify_noanchor.py      # link.noanchor
python3 ../tools/verify_metadup.py        # meta.duplicate
python3 ../tools/verify_titledup.py       # title.duplicate
python3 ../tools/verify_rest.py           # title.too_short / soft404 /
                                           # http.mixed_content / img.alt.generic
python3 ../tools/verify_fixed.py <rule>   # img.alt.missing 等
python3 ../tools/verify_sitemap2.py       # sitemap.missing
```

## 结果

| 规则 | 抽样 | 真问题 | 误报 | 存疑 | 备注 |
|---|---|---|---|---|---|
| `title.missing` | 12 | 11 | 1 | 0 | 唯一误报是 shopify 社区页，实际有 description |
| `canonical.missing` | 15 | 13 | 0 | 2 | |
| `h1.missing` | 15 | 15 | 0 | 0 | |
| `title.too_long` | 12 | 12 | 0 | 0 | |
| `noindex.present` | 12 | 12 | 0 | 0 | |
| `title.missing`（另一批） | 8 | 7 | 0 | 0 | 1 条回源抓不到 |
| `h1.multiple` | 5 | 5 | 0 | 0 | |
| `canonical.conflict` | 7 | 7 | 0 | 0 | 修正判据后 |
| `img.alt.missing` | 14 | 14 | 0 | 0 | 修正判据后 |
| `meta.duplicate` | 10 | 8 | 0 | 2 | 补语言头+实体解码后 |
| `title.duplicate` | 8 | 6 | 0 | 2 | 2 条页面跳去了别的域 |
| `title.too_short` | 4 | 4 | 0 | 0 | 逐条跑，不抽样 |
| `soft404` | 6 | 4 | 0 | 2 | 2 条页面内容已变 |
| `http.mixed_content` | 2 | 2 | 0 | 0 | 逐条跑 |
| `img.alt.generic` | 1 | 1 | 0 | 0 | 逐条跑 |
| `sitemap.missing` | 10 | 8 | **2** | 0 | 查出一个真 bug，已修 |
| `link.noanchor` | 10 | 6 | 4 | 0 | 4 条差 1 个，判为规则站得住 |
| `robots.blocks_own_site` | 1 | 0 | 1 | 0 | 判据存疑，未查实 |

## 查出的真 bug（已修）

`sitemap.py` 判「这是 sitemap 索引」的启发式：

```python
is_index = "<sitemapindex" in content or (
    depth == 0 and all(not loc.endswith((".html", "/")) for loc in locs[:5])
)
```

现代站点 URL 普遍不带 `.html` 也不带尾斜杠，于是 `bellroy.com` 那种
91KB、512 条 loc 的真 urlset 被当成索引，跑去把**产品页当子 sitemap
逐个加载**，全失败 → 报「缺 sitemap」。

58 条 `sitemap.missing` 里 **12 条**是这个 bug（收紧判据后：`/sitemap.xml`
返回 200 却 `ok=False`，且 `tried_paths` 混进普通页面 URL）。
改成看根元素 `<urlset>` / `<sitemapindex>`。12 个真站复验：改前全报错，
改后全闭嘴。回归测试在 `backend/tests/test_sitemap_index_detection.py`。

## 我自己的核对器错过的几处

这些不是规则错，是核对器错。**记下来是因为每次都栽在同一类地方**：

1. **规则报的是子集，不要求相等。** `img.alt.missing` 我要求「规则报数 ==
   原文无 alt 数」，slashdot 是 1 vs 21——提取层看到的图永远比原文少
   （懒加载、noscript、未进 DOM）。方向是**少报**不是报错。
2. **curl 必须带 `Accept-Language: zh-CN`。** crawler 带了，接了翻译的站
   （Discourse / bellroy / airbnb）会整页机器翻译。不带就拿到英文，
   跟报告里的中文永远对不上。这一条害我误判了 `meta.duplicate` 4 条。
3. **HTML 实体要解码。** `PagerDuty&#x27;s` vs `PagerDuty's`。
4. **没测到 ≠ 不存在。** 回访失败、页面是 JS 壳、被跳去了别的域——一律存疑，
   不记误报。
5. **规则源码先读。** 不知道 `link.noanchor` 有 6 层锚文本兜底、
   `img.alt.missing` 只算「完全没有 alt 属性」，就写不出对的核对器。

## 还没核的

- `link.noanchor` 剩余 24 条未跑（6 层兜底已对齐，抽 10 条先看结果）
- `meta.duplicate` / `title.duplicate` 剩余样本未跑
- `robots.blocks_own_site` 那 1 条判据没查实
- `soft404` 2 条存疑：页面内容已变，判不了

## 所以 README 里没有准确率数字

抽样只覆盖了报得最多的十几条规则，483 条里绝大多数没核过。
拿没测的数据说「97%」是充数。想自己验就用上面的脚本。