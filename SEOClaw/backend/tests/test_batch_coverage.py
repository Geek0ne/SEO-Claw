"""分批跑完整站：hit_page_limit 的口径测试（技术债最后一条）。

## 背景：为什么这条要改口径而不是加功能

PLAN 的技术债写着「`hit_page_limit` 时一律不下结论，即使已抓 1000 页」。
原实现看起来像「没做完就别下结论」的谨慎，实际是**站点级规则永久沉默**：

    hit_page_limit = aborted_reason or len(pages) >= cfg.max_pages

分批跑站时，**每一趟都以打满 max_pages 收尾**。于是这个标志永远为 True，
`has_enough_data()` 永远返回 False，`orphan.page` 永远不触发——
「分批跑完整站」这个能力等于白做。

## 正确的口径

真正该问的不是「本趟有没有打满上限」，而是「**frontier 还有没有剩**」：

- frontier 空 → 该抓的都抓完了，覆盖率是完整的，站点级规则该发话
- frontier 没空 → 还有没抓的（撞上限 / 深度上限 / robots 拦了），
  「没发现指向它的内链」就只是「还没抓到」，必须保持沉默

## 实测依据（2026-10-02）

三趟同 checkpoint：max-pages 3 → 6 → 9，每趟都真的多抓了页
（jsonl 从 3 → 6 → 9）。**分批机制本身没问题**，问题纯在标志口径。
"""

from __future__ import annotations

import pytest

from app.audit.engine import RuleContext
from app.models import Market, Page


def _ctx(**kw) -> RuleContext:
    base = dict(domain="demo.test", markets=[Market.BASE])
    base.update(kw)
    return RuleContext(**base)


# --------------------------------------------------------------------------
# RuleContext.has_enough_data —— 口径改动的直接受益者
# --------------------------------------------------------------------------


def test_drained_frontier_unlocks_site_level_rules():
    """★ 核心断言：frontier 排空时，站点级规则该发话。

    这就是改动前永远走不到的那一步。
    """
    ctx = _ctx(crawled=40, discovered=40, hit_page_limit=False)
    assert ctx.has_enough_data(min_pages=20, min_coverage=0.5) is True


def test_non_drained_frontier_keeps_rules_silent():
    """frontier 没排空 → 保持沉默。「没看到」不能当「没有」。

    ⚠️ ``hit_page_limit`` 要作为 ``RuleContext`` 的**直接字段**传，
    不是塞进 ``site_facts``。两处同名极易看错：
    ``has_enough_data()`` 读的是 ``self.hit_page_limit``（字段），
    只有 ``run_audit()`` 才会从 site_facts 里把它取出来灌进字段。
    我第一版就是塞进 site_facts，结果门槛形同虚设 —— 测试反而是绿的。
    """
    ctx = _ctx(crawled=1000, discovered=900, hit_page_limit=True)
    assert ctx.has_enough_data() is False


def test_hit_page_limit_still_wins_when_coverage_looks_complete():
    """⚠️ 满覆盖率也不能盖过 hit_page_limit。

    构造一个「自相矛盾」的组合：crawled 超过 discovered（覆盖率 >1），
    但 hit_page_limit 为 True。这种情况下仍必须沉默——
    覆盖率算得再漂亮，也可能是 visited 里混了没真正抓到的 URL。
    """
    ctx = _ctx(crawled=200, discovered=100, hit_page_limit=True)
    # coverage 被 min(1.0, ...) 夹住，crawled 再大也只会等于 1.0
    # （我第一版断言 >1.0，被自己的实现打回 —— 那不是 bug，是钳位设计。）
    assert ctx.coverage == 1.0
    assert ctx.has_enough_data() is False, (
        "覆盖率算满也不能盖过 hit_page_limit"
    )


# --------------------------------------------------------------------------
# CLI 的口径换算
# --------------------------------------------------------------------------


class _FakeCrawler:
    """只提供 CLI 读的那两个属性。"""

    def __init__(self, *, aborted_reason=None, frontier_drained=None):
        self.aborted_reason = aborted_reason
        if frontier_drained is not None:
            self.frontier_drained = frontier_drained


def _hit_page_limit(crawler) -> bool:
    """复刻 cli.py 里的换算逻辑。

    故意不 import 私 Helper —— 这段逻辑要在这份测试里独立存在一份，
    否则改了cli.py 这里跟着变，测试就成了同义反复。
    """
    return bool(
        getattr(crawler, "aborted_reason", None)
        or not getattr(crawler, "frontier_drained", False)
    )


def test_batched_run_no_longer_sets_hit_page_limit():
    """★ 分批跑的收尾场景：打满了上限，但 frontier 排空了。

    改动前：``len(pages) >= cfg.max_pages`` → True → 孤岛页永远沉默。
    改动后：frontier 空 → False → 站点级规则正常发话。
    """
    crawler = _FakeCrawler(frontier_drained=True)
    assert _hit_page_limit(crawler) is False


def test_truly_truncated_run_still_sets_hit_page_limit():
    """真的撞上限截断（frontier 仍有剩余）→ 必须保持沉默。"""
    crawler = _FakeCrawler(frontier_drained=False)
    assert _hit_page_limit(crawler) is True


def test_aborted_run_still_sets_hit_page_limit():
    """熔断中止（aborted_reason）优先于 frontier 状态。"""
    crawler = _FakeCrawler(aborted_reason="too_many_errors", frontier_drained=True)
    assert _hit_page_limit(crawler) is True


def test_missing_attribute_fails_safe():
    """⚠️ 属性缺失时按「未排空」处理 → 沉默。

    fail-safe 方向必须是沉默：宁可少报，不可把「没抓到」说成「没有」。
    （如果默认成 True，一个没设置该属性的旧爬虫对象会让所有站点级规则
    在覆盖率不足时直接开火——正好把这次修的 bug 反过来又犯一遍。）
    """
    crawler = _FakeCrawler()
    assert not hasattr(crawler, "frontier_drained")
    assert _hit_page_limit(crawler) is True


# --------------------------------------------------------------------------
# 端到端：孤岛页规则
# --------------------------------------------------------------------------


def test_orphan_rule_fires_after_complete_batched_scan():
    """完整跑完后，有真孤岛就必须报出来。"""
    from app.audit.engine import run_audit
    from tests.test_rules import html  # 复用现成样本构造

    pages = [
        Page.model_validate(
            __import__("app.extract", fromlist=["extract_page"]).extract_page(
                f"https://demo.test/p{i}", html(title=f"标题{i}")
            ).model_dump()
        )
        for i in range(40)
    ]
    issues, _ = run_audit(
        pages,
        "demo.test",
        [Market.BASE],
        site_facts={"discovered_count": 40, "hit_page_limit": False},
    )
    assert [i for i in issues if i.code == "orphan.page"], (
        "跑完整个站后，孤岛页检测必须发话"
    )


def test_orphan_rule_still_silent_on_truncated_scan():
    """反向用例：截断了就闭嘴。防止这个改动变成「永远开火」。"""
    from app.audit.engine import run_audit
    from tests.test_rules import html
    from app.extract import extract_page

    pages = [extract_page(f"https://demo.test/p{i}", html(title=f"标题{i}"))
             for i in range(40)]
    issues, _ = run_audit(
        pages,
        "demo.test",
        [Market.BASE],
        site_facts={"discovered_count": 400, "hit_page_limit": True},
    )
    assert not [i for i in issues if i.code == "orphan.page"]