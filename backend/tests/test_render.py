"""
JS 渲染层测试（Playwright）。

为什么这层必须优雅降级
----------------------
浏览器二进制可能没装、下载失败、启动慢。任何一个环节出问题，
都不该让整个工具不可用——SEO 工具的价值在于「随时能跑出一份报告」，
所以这里的每条路径都必须是"降级并记录"，而不是"抛异常"。

真实动机：go.dev 是 Next.js 站点，静态 HTML 里几乎没有 <a>，
不开渲染只抓到 1 个 URL。这测试就是防止「加了渲染开关却没接上」。
"""

from __future__ import annotations


import asyncio

import pytest

from seoclaw.crawler import CrawlConfig, Crawler
from seoclaw.models import Page
from seoclaw.render import RenderConfig, Renderer


@pytest.fixture(autouse=True)
def _clear_stale_running_loop():
    """⚠️ Playwright sync API 会把「loop 正在运行」的标记泄漏在调用线程
    （pytest 主线程）上：跑过本模块之后，任何用
    ``loop.run_until_complete`` 驱动协程的测试都会报
    ``RuntimeError: Cannot run the event loop while another loop is
    running``。

    这个雷以前没炸纯属运气——用 run_until_complete 的模块（test_db、
    test_scheduler）按字母序排在 test_render 前面/后面不凑巧。2026-10-20
    新增 test_scheduler（排在 test_render 之后）才炸出来：9 个用例全
    error，而 test_render 单跑、test_scheduler 单跑都绿。

    清标记用的是 asyncio 的准内部接口 ``_set_running_loop(None)``：
    没有公开等价物，且这里能确定没有真的 loop 在跑（测试是同步的）。
    放在每条用例之后清，而不是只在模块尾清——单跑任意一条都该干净。
    """
    yield
    asyncio.events._set_running_loop(None)


# --------------------------------------------------------------------------
# 启发式：只对「静态 HTML 看起来是 SPA 空壳」的页面渲染
# --------------------------------------------------------------------------


def _page(**kw) -> Page:
    base = dict(url="https://demo.test/p", status_code=200, is_html=True)
    base.update(kw)
    return Page(**base)


def test_spa_shell_needs_render():
    """既没内链也没正文 → 典型 SPA 空壳，该渲染。"""
    c = Crawler(CrawlConfig(render_js=True))
    assert c._needs_render(_page(internal_link_count=0, word_count=0))


def test_content_page_does_not_need_render():
    """正常文章页不需要渲染——渲染会慢 10~50 倍，绝不能无条件开。"""
    c = Crawler(CrawlConfig(render_js=True))
    assert not c._needs_render(_page(internal_link_count=30, word_count=2000))


def test_error_page_never_needs_render():
    c = Crawler(CrawlConfig(render_js=True))
    assert not c._needs_render(_page(error="timeout", is_html=False, word_count=0))
    assert not c._needs_render(_page(status_code=404, internal_link_count=0, word_count=0))


def test_threshold_is_configurable():
    """阈值可调：有的站点导航就是少，规则要能放宽。"""
    strict = Crawler(CrawlConfig(render_js=True, render_link_threshold=0,
                                render_word_threshold=0))
    loose = Crawler(CrawlConfig(render_js=True, render_link_threshold=50,
                                render_word_threshold=5000))
    p = _page(internal_link_count=10, word_count=500)
    assert not strict._needs_render(p)
    assert loose._needs_render(p)


def test_render_disabled_by_default():
    """默认不开渲染：不能因为加了功能就让默认行为变慢。"""
    assert CrawlConfig().render_js is False


# --------------------------------------------------------------------------
# 降级：任何失败都不能让扫描崩掉
# --------------------------------------------------------------------------


def test_render_returns_disabled_when_not_configured():
    r = Renderer(RenderConfig(enabled=False))
    html, status = r.render("https://demo.test/")
    assert html is None
    assert status == "disabled"


def test_render_never_raises_on_unavailable_browser():
    """浏览器不可用时返回 unavailable，而不是抛异常。"""
    r = Renderer(RenderConfig(enabled=True))
    # 不预先启动浏览器，直接调用；未安装时应降级而非崩溃
    html, status = r.render("https://this-domain-does-not-exist.invalid/")
    assert html is None or isinstance(html, str)
    assert status in ("unavailable", "failed")


def test_renderer_stats_present():
    """统计字段要存在，调用方要能报告「渲染了多少页、失败多少页」。"""
    r = Renderer(RenderConfig(enabled=False))
    assert set(r.stats) == {"rendered", "fallback", "failed"}


def test_renderer_is_singleton():
    """浏览器是重量级资源，必须单例，不能每次调用起一个。"""
    a = Renderer.instance(RenderConfig(enabled=False))
    b = Renderer.instance()
    assert a is b
    Renderer.reset_instance()


# --------------------------------------------------------------------------
# 配置透传
# --------------------------------------------------------------------------


def test_crawler_creates_renderer_only_when_enabled():
    """不开渲染就不建浏览器实例——省几百 MB 内存。"""
    assert Crawler(CrawlConfig(render_js=False))._renderer is None
    assert Crawler(CrawlConfig(render_js=True))._renderer is not None


def test_render_status_recorded_on_page():
    """渲染状态要落到 Page 上：规则要能区分「查过没问题」和「根本没查」。"""
    p = _page()
    p.render_status = "unavailable"
    assert p.render_status == "unavailable"
