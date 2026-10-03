"""sitemap 索引判定的回归测试。

背景（2026-10-03）：真实 bug，不是设想。

`bellroy.com` 有 91KB 的真 sitemap（512 条 loc），但工具报「缺 sitemap」。
根因在 `_load_inner` 判定「这是 sitemapindex（子文件列表）」的启发式：

    is_index = "<sitemapindex" in content or (
        depth == 0 and all(not loc.endswith((".html", "/")) for loc in locs[:5])
    )

bellroy 的 loc 长这样：

    /collection/colorway/navy
    /products/venture-sling

现代站点的 URL 普遍既不带 `.html` 也不带尾斜杠，于是「前 5 条都不以
/ 或 .html 结尾」这个条件成立 → 真 urlset 被误判成索引 → 逐条去加载
**产品页**当子 sitemap（报告的 tried_paths 里全是 /products/... 和
/journal/...，那正是这个 bug 的指纹）→ 全失败 → ok=False → 报缺 sitemap。

150 站实测：58 条 sitemap.missing 里 **19 条**是这个 bug 造成的
（vercel、nodejs.org、docusaurus.io、hex.pm、shopify… 全是现代 URL 风格）。

修法：判据改成看**根元素**——`<urlset>` 与 `<sitemapindex>` 是两个
互斥的根标签，规范上不会混。
"""
from __future__ import annotations

import httpx

from seoclaw.sitemap import SitemapFinder

MODERN_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://bellroy.com/collection/colorway/navy</loc></url>
  <url><loc>https://bellroy.com/collection/venture</loc></url>
  <url><loc>https://bellroy.com/journal/carry-portraits-anna-marrone</loc></url>
  <url><loc>https://bellroy.com/corporate-gifting</loc></url>
  <url><loc>https://bellroy.com/products/venture-sling</loc></url>
</urlset>
"""

# energy.gov 那种真索引（见 sitemap.py 里 SITEMAP_TIME_BUDGET 的注释）
REAL_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.energy.gov/sitemap/sitemap-part-01.xml</loc></sitemap>
  <sitemap><loc>https://www.energy.gov/sitemap/sitemap-part-02.xml</loc></sitemap>
</sitemapindex>
"""

CHILD_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.energy.gov/some/page</loc></url>
</urlset>
"""


def _finder(responses: dict[str, tuple[int, str]]) -> SitemapFinder:
    """用 MockTransport 造一个 SitemapFinder，不发真请求。

    `_client` 是构造时自建的 httpx.Client，这里换掉它的 transport。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in responses:
            status, body = responses[url]
        else:
            status, body = 404, "not found"
        return httpx.Response(status, text=body,
                              headers={"content-type": "application/xml"})

    finder = SitemapFinder(user_agent="test-agent", timeout=1.0)
    finder._client = httpx.Client(  # noqa: SLF001 — 测试要替换内部依赖
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        headers={"User-Agent": "test-agent"},
    )
    return finder


def test_modern_urlset_is_not_mistaken_for_index():
    """loc 不带 .html / 尾斜杠的 urlset，必须当 urlset 收下。

    修复前这段会挂：finder 会把 /collection/... 当子 sitemap 去加载。
    """
    root = "https://bellroy.com/sitemap.xml"
    finder = _finder({
        root: (200, MODERN_URLSET),
        "https://bellroy.com/robots.txt": (404, ""),
    })
    try:
        result = finder.discover("https://bellroy.com/")
    finally:
        finder.close()

    assert result.found is True, "有真 sitemap 却报没有——就是那 19 条误报的成因"
    assert "https://bellroy.com/collection/colorway/navy" in result.urls

    # 关键：不该再去加载产品页/博客页当子 sitemap
    tried = [t["url"] for t in result.tried]
    assert not any(u.startswith("https://bellroy.com/products/") for u in tried), \
        "又去把产品页当子 sitemap 加载了"
    assert not any(u.startswith("https://bellroy.com/journal/") for u in tried), \
        "又去把博客页当子 sitemap 加载了"
    assert not any(u.startswith("https://bellroy.com/collection/") for u in tried), \
        "又去把集合页当子 sitemap 加载了"


def test_real_sitemapindex_still_recurses():
    """真索引必须继续往下递归——修复不能把索引功能打死。"""
    index = "https://www.energy.gov/sitemap.xml"
    child1 = "https://www.energy.gov/sitemap/sitemap-part-01.xml"
    child2 = "https://www.energy.gov/sitemap/sitemap-part-02.xml"
    finder = _finder({
        "https://www.energy.gov/robots.txt": (404, ""),
        index: (200, REAL_INDEX),
        child1: (200, CHILD_URLSET),
        child2: (200, CHILD_URLSET),
    })
    try:
        result = finder.discover("https://www.energy.gov/")
    finally:
        finder.close()

    assert result.found is True
    tried = [t["url"] for t in result.tried]
    assert child1 in tried, "该去递归子 sitemap"
    assert child2 in tried, "该去递归子 sitemap"
    assert "https://www.energy.gov/some/page" in result.urls


def test_no_sitemap_anywhere_reports_not_found():
    """真没有时仍然要报没有——别修成永远沉默。"""
    finder = _finder({"https://nosuchsite.example/robots.txt": (404, "")})
    try:
        result = finder.discover("https://nosuchsite.example/")
    finally:
        finder.close()

    assert result.found is False
    assert result.tried, "「试过但没找到」必须留痕，否则证据恒为空"


def test_garbage_without_root_element_is_not_treated_as_index():
    """根元素被截掉/HTML 伪装时，宁可当 urlset。

    反过来判会重演那个 bug：把几百个页面 URL 挨个当子 sitemap 加载，
    撞死 MAX_CHILD_ATTEMPTS 还什么都拿不到。
    """
    root = "https://example.com/sitemap.xml"
    body = "<loc>https://example.com/a/b/c</loc>" * 3  # 没有根元素
    finder = _finder({
        "https://example.com/robots.txt": (404, ""),
        root: (200, body),
    })
    try:
        result = finder.discover("https://example.com/")
    finally:
        finder.close()

    tried = [t["url"] for t in result.tried]
    assert not any(u.startswith("https://example.com/a/") for u in tried), \
        "不该递归去加载 a/b/c"
