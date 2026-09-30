"""客户端渲染失败壳的识别 —— M0 第三批误报回归。

为什么要有这个测试
------------------
pypi.org 抓取时有 3 个 URL 返回 **HTTP 200**，但正文不是页面，而是浏览器
的 JS 报错壳：

    "A required part of this site couldn't load. This may be due to a
     browser extension, network issues, or browser settings."

于是 4 条规则对着这个壳子齐刷刷开火，各报 2~3 条误报：
h1.missing / meta.missing / canonical.missing / soft404。
复测时同一批 URL 全部恢复正常 —— 说明是当时前端加载失败，**不是站点
没做 SEO，更不是我们解析错了**。

这跟「4xx 页面的 noindex 不该报 CRITICAL」是同一类病，但修的位置不同：
那个在规则层，这个必须在提取层。页面级规则数量多、每条都要单独加
「跳过失败页」的守卫，漏一条就漏一批；提取层标一次 `page.error`，
审计引擎 `if not page.is_html or page.error: continue` 一次就全挡住了。

三个条件必须同时成立（缺一不可）
--------------------------------
1. 正文里有客户端失败的文案 —— 这是**正面证据**，服务器自己承认失败了
2. 页面确实是客户端框架（有挂载点 / 框架特征）
3. 正文很短 —— 真内容页不会同时命中失败文案

⚠️ 条件 3 是「辅助」不是「主判据」。曾经有个更早的版本在核对器里用
「页面薄」当反爬证据，把 115 条正常样本踢出分母换了个漂亮数字——
页面内容少只说明它是 thin page，它仍然是**真页面**，我们观察到了就该判。
判 failed 要求的是「没观察到」，那必须有失败的正面痕迹。
"""
from __future__ import annotations

import pytest

from app.extract import _looks_client_render_failure, extract_page
from app.models import Page

# pypi 现场抓到的真实报错壳（正文 209 词）
PYPI_SHELL = """<!DOCTYPE html>
<html lang="en">
<head><title>PyPI</title></head>
<body>
<div id="root"></div>
<script src="/static/js/main.abc123.js"></script>
<div class="shell">
  <h1>A required part of this site couldn't load.</h1>
  <p>This may be due to a browser extension, network issues,
     or browser settings.</p>
</div>
</body>
</html>
"""
# ⚠️ 报错文案必须放在**正文 div** 里，不能放 <noscript>。
# 我第一版把它塞进 <noscript>，四个参数化用例全挂——因为 _extract_text
# 的降级路径会主动删掉 noscript 标签，文案从一开始就不在 page.text 里。
# 真实 pypi 样本的 soft404 evidence 记着 word_count=209、text_preview 就是
# 那句报错文案，说明真实页面的报错文案**确实在正文里**。样本放错位置了，
# 规则没错。改样本，不是改断言去迁就实现。


def _page_from(html: str) -> Page:
    return extract_page(
        url="https://example.com/p",
        raw_html=html,
        status_code=200,
        content_type="text/html",
        final_url="https://example.com/p",
        depth=0,
    )


# --------------------------------------------------------------------------
# 正例：确实该判失败
# --------------------------------------------------------------------------


def test_pypi_shell_is_detected():
    """真实样本：pypi 那个 JS 报错壳必须被抓到。"""
    page = _page_from(PYPI_SHELL)
    assert _looks_client_render_failure(PYPI_SHELL, page), "pypi 报错壳没被识别"


def test_shell_marks_page_error_so_rules_skip_it():
    """关键：标记 page.error，审计引擎会跳过所有页面级规则。"""
    page = _page_from(PYPI_SHELL)
    assert page.error == "client_render_failed"
    # 引擎的跳过条件：not is_html or error
    assert not (page.is_html and not page.error)


# --------------------------------------------------------------------------
# 反例：这些都**不能**判 failed，否则就是把真问题吞掉
# --------------------------------------------------------------------------


def test_normal_article_page_not_flagged():
    """正文长、有内容 —— 即便里面有「error」字样也不能判失败。"""
    html = """<html lang="en"><head><title>Blog</title></head><body>
    <div id="root"></div>
    <article><h1>How to debug errors in production</h1>
    <p>""" + ("This paragraph explains the error handling strategy. " * 60) + """
    </p></article></body></html>"""
    page = _page_from(html)
    assert page.error is None


def test_thin_but_real_page_not_flagged():
    """⚠️ 这条是本测试文件存在的核心理由。

    一个真实的、就是很短的页面（落地页 / 感谢页），我们**观察到了**它，
    就应该拿规则去量它。判 failed 等于把观察结果丢掉。
    """
    html = """<html lang="en"><head><title>Thanks</title></head><body>
    <div id="root"></div>
    <h1>Thank you</h1><p>Your order has been received.</p>
    </body></html>"""
    page = _page_from(html)
    assert page.error is None, "薄但真实的页面被判失败 = 漏报真问题"


def test_blank_page_not_flagged_as_client_failure():
    """空页面确实是问题（soft404 该报），但那是「页面本身空」，
    不是「客户端加载失败」——两者的 fix_hint 完全不同，不能混。"""
    html = "<html><head></head><body></body></html>"
    page = _page_from(html)
    assert page.error is None


def test_failure_text_without_framework_not_flagged():
    """服务器渲染的页面里出现「chunk load error」这类词（比如技术博客），
    没有客户端框架就不该判失败——那是文章内容。"""
    html = """<html lang="en"><head><title>Chunk load error fixed</title></head>
    <body><h1>Fixing chunk load error</h1>
    <p>""" + ("A chunk load error happens when the bundle fails. " * 40) + """
    </p></body></html>"""
    page = _page_from(html)
    assert page.error is None


@pytest.mark.parametrize(
    "shell_text",
    [
        "A required part of this site couldn't load.",
        "A required part of this site could not load.",
        "Application error: a client-side exception has occurred",
        "ChunkLoadError: Loading chunk 42 failed",
    ],
)
def test_various_shell_messages(shell_text: str):
    """不同框架的报错文案不一样，但都要认出来。"""
    html = f"""<html><head><title>t</title></head><body>
    <div id="app"></div><script src="/app.js"></script>
    <div class="shell">{shell_text}</div></body></html>"""
    page = _page_from(html)
    assert _looks_client_render_failure(html, page), shell_text
