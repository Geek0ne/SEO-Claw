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

| 规则 | 核对条数 | 真问题 | 误报 | 存疑 | 备注 |
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
| `meta.duplicate` | 25 | 23 | **0** | 2 | 全量跑的，补前缀比对后 |
| `title.duplicate` | 16 | 12 | **0** | 4 | 全量跑的，补壳检测后 |
| `title.too_short` | 4 | 4 | 0 | 0 | 逐条跑，不抽样 |
| `soft404` | 6 | 4 | 0 | 2 | 2 条页面内容已变 |
| `http.mixed_content` | 2 | 2 | 0 | 0 | 逐条跑 |
| `img.alt.generic` | 1 | 1 | 0 | 0 | 逐条跑 |
| `sitemap.missing` | 10 | 8 | **2** | 0 | 查出一个真 bug，已修 |
| `link.noanchor` | 34 | 23 | **0** | 10 | 全量跑的，换判据后 |
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
6. **规则报的是子集，我却要求数字相等。** `link.noanchor` 我第一版要求
   `实测 == 规则报数`，全量 34 条判出 15 条误报。实跑看：slashdot 规则报 6
   我数 24 —— 规则只是**少报**，不是报错。这跟第 1 条（img.alt）是同一个错，
   我改了那边忘了改这边。两处一起修后误报归零。
7. **我数得比规则少时，记「存疑」不是「误报」。** csdn 规则报 25 我数 1、
   edx 报 11 我数 0 —— 页面这几天变了，我抓到的不是当初那份。这类我判不了。
8. **页面上看不见的 `<a>` 不算。** 我 regex 到 slashdot 的 270 个 `<a>`，
   6 个藏在 `<script>`/`<noscript>` 里。不去掉就会把 JS 模板里的字符串
   当成页面上的空锚。
9. **规则存的是截断值，我拿它跟全量比。** `automattic` 那条 evidence 里是
   `desc[:200]`（199 字），原文 361 字，**前缀完全相同**。只能比前缀。
10. **回访可能拿到「跳转壳」而不是页面。** airbnb 回访返回的是
    `<title>重定向到zh.airbnb.com</title>` + `onload` 提交 POST 表单，
    curl `-L` 停在 `www.airbnb.com`，域没变——我那道「换域才存疑」的
    守卫拦不住它。
11. **实体和空白要归一化。** `PagerDuty&#x27;s`、`&nbsp;`（不换行空格 `\xa0`）
    解出来跟规则那边对不上。要先把实体解开、把所有空白折叠成普通空格。

5. **规则源码先读。** 不知道 `link.noanchor` 有 6 层锚文本兜底、
   `img.alt.missing` 只算「完全没有 alt 属性」，就写不出对的核对器。

## 还没核的

- `robots.blocks_own_site` 那 1 条判据没查实
- 若干「存疑」：页面这几天变了，或跳去了别的域，我抓到的不是当初那份，判不了
- 其余规则的样本仍是抽样，不是全量

## 所以 README 里没有准确率数字

抽样只覆盖了报得最多的十几条规则，483 条里绝大多数没核过。
拿没测的数据说「97%」是充数。想自己验就用上面的脚本。