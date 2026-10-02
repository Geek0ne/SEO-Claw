"""代理 IP 轮换测试。

重点是两条**看起来会工作、实际不工作**的坑：

1. ``visited.add(key)`` 发生在 ``_fetch`` **之前**。不把 URL 从 visited 里
   摘掉再放回 frontier，轮换 IP 之后这个页面永远不会重试 —— 代理池配得
   再大也白配。
2. 重试不设上限就是活锁：每个代理都被封一次，无限循环，扫描永远跑不完。
   这比直接中止更糟。

全程不碰真代理：用 MockTransport 假造 403/429。
"""

from __future__ import annotations

import httpx

from seoclaw.crawler import CrawlConfig, Crawler


def _cfg(**kw) -> CrawlConfig:
    base = dict(
        max_pages=3,
        per_domain_rps=1000.0,
        total_rps=1000.0,
        respect_robots=False,
        use_sitemap=False,
        adaptive_backoff=False,
    )
    base.update(kw)
    return CrawlConfig(**base)


def test_no_proxies_by_default():
    """默认不走代理 —— 与引入轮换之前的行为必须逐字一致。"""
    c = Crawler(_cfg())
    try:
        assert c.current_proxy is None
        assert c.rotate_proxy() is False, "没有代理池时不该声称换成功了"
        assert c.proxy_rotations == 0
    finally:
        c.close()


def test_rotate_cycles_through_pool():
    c = Crawler(_cfg(proxies=("http://p1", "http://p2", "http://p3")))
    try:
        assert c.current_proxy is None, "起步应为直连，第一次轮换才进池"
        assert c.rotate_proxy() is True and c.current_proxy == "http://p1"
        assert c.rotate_proxy() is True and c.current_proxy == "http://p2"
        assert c.rotate_proxy() is True and c.current_proxy == "http://p3"
        assert c.rotate_proxy() is True and c.current_proxy == "http://p1", "应取模回绕"
        assert c.proxy_rotations == 4
    finally:
        c.close()


def test_single_proxy_is_not_a_rotation():
    """只有一个代理时「换了」等于没换，必须返回 False。

    返回 True 会让调用方把失败页重排进 frontier，然后从同一个被封的 IP
    再请求一次 —— 白白多一轮延迟，报告还多一条超时。
    """
    c = Crawler(_cfg(proxies=("http://only",)))
    try:
        assert c.rotate_proxy() is True  # 直连 → p1，算一次
        assert c.rotate_proxy() is False  # p1 → p1，没换
        assert c.proxy_rotations == 1
    finally:
        c.close()


def test_rotate_rebuilds_client_with_new_proxy():
    """⚠️ httpx 0.28 只剩单数 ``proxy=``，换代理在实现上必须**重建 Client**。

    这里锁的就是「真的换了 proxy 参数」——否则会留下一个看似轮换、
    实际还在用旧出口的 client。
    """
    c = Crawler(_cfg(proxies=("http://p1", "http://p2")))
    try:
        first = c.client
        c.rotate_proxy()
        assert c.client is not first, "轮换必须换掉 Client 实例"
    finally:
        c.close()


def _crawler_returning(statuses, **cfgkw):
    """造一个按调用顺序返回状态码的 crawler。"""
    seq = list(statuses)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        code = seq[i]
        if code == 200:
            return httpx.Response(
                200,
                content=b"<html lang='en'><head><title>ok</title></head>"
                b"<body><p>real content here</p></body></html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(code, headers={"content-type": "text/html"})

    c = Crawler(_cfg(**cfgkw))
    # ⚠️ 必须打在 `_build_client` 上，不能打 `c.client`。
    #
    # 我第一版写的是 `c.client = MockTransport(...)`，于是
    # rotate_proxy() 一执行就 close() 掉那个 mock client、再用
    # _build_client() 重建一个走真代理的 —— mock 当场失效，
    # 重试请求真的去连 http://p1 了。
    # 症状是「轮换明明打了日志、但 mock 调用次数还是 1」，
    # 看起来像轮换没重试，其实是测法接错了缝。
    c._build_client = lambda: httpx.Client(transport=httpx.MockTransport(handler))
    c.client = c._build_client()
    return c, calls


def test_blocked_page_is_retried_on_new_proxy():
    """⚠️ 核心用例：第一个 IP 被封，换 IP 后**同一个 URL 必须真的重试**。

    不重试的表现是「代理池配了也没用」——而且报告里看起来是抓完了，
    只是那个页面是 403，没有任何异常信号。
    """
    c, calls = _crawler_returning([429, 200], proxies=("http://p1", "http://p2"))
    try:
        pages = c.crawl("https://x.test/")
        assert calls["n"] >= 2, "被封后必须发第二次请求"
        assert c.proxy_rotations >= 1
        assert any(p.status_code == 200 for p in pages), f"换 IP 后应拿到 200：{pages}"
        # 被封的那次失败页不该留在报告里
        assert not any(p.status_code == 429 for p in pages), "失败页不该入报告"
    finally:
        c.close()


def test_retries_are_bounded_no_livelock():
    """⚠️ 全部代理都被封 → 到上限就停，不能无限重试。

    活锁比直接中止更糟：报告永远出不来，而且看不出在忙什么。
    """
    c, calls = _crawler_returning(
        [429], proxies=("http://p1", "http://p2"), max_pages=3
    )
    try:
        pages = c.crawl("https://x.test/")
        # 每个代理试一次（起步直连也算一次尝试），不该无限增长
        assert calls["n"] <= len(c.config.proxies) + 2, f"请求次数失控：{calls['n']}"
        assert pages == [] or all(p.status_code != 200 for p in pages)
    finally:
        c.close()


def test_no_proxy_pool_does_not_requeue():
    """没有代理池时不该重排 URL —— 否则每个失败页都白请求一次。"""
    c, calls = _crawler_returning([429], proxies=())
    try:
        c.crawl("https://x.test/")
        assert calls["n"] == 1, f"无代理池不该重试，实际请求 {calls['n']} 次"
    finally:
        c.close()