"""处方包（fixpack）测试。

约定：不碰网络、不碰数据库——处方层的输入是「一次扫描的 pages + issues」，
这里用手造的 Page/Issue 钉住改写逻辑，另加一条与真实规则引擎的集成用例
（保证「处方覆盖的 code」与「规则真的会产出的 code」对得上）。
"""

from __future__ import annotations

from seoclaw.extract import extract_page
from seoclaw.fixpack import (
    Confidence,
    build_fixpack,
    render_fixpack,
    render_fixpack_csv,
    render_fixpack_diff,
    render_fixpack_markdown,
)
from seoclaw.models import ImageRef, Issue, Market, Page, Severity


def _page(url: str = "https://demo.test/shoes", **kw) -> Page:
    defaults = dict(
        url=url,
        final_url=url,
        status_code=200,
        is_html=True,
        content_hash="h",
    )
    defaults.update(kw)
    return Page(**defaults)


def _issue(code: str, severity: Severity = Severity.MEDIUM, url: str | None = None, **kw) -> Issue:
    return Issue(code=code, severity=severity, url=url, **kw)


# --------------------------------------------------------------------------
# 页面级字段改写
# --------------------------------------------------------------------------


def test_title_too_long_is_clipped_and_says_draft():
    long_title = "超长的中文标题" * 8  # 56 字，远超 30 字预算
    p = _page(title=long_title, title_length=len(long_title))
    pack = build_fixpack([p], [_issue("title.too_long", Severity.MEDIUM, p.url)], "demo.test")

    acts = [a for a in pack.actions if a.field == "title"]
    assert len(acts) == 1
    a = acts[0]
    assert a.before == long_title
    assert len(a.after) <= 30
    assert a.after.endswith("…")
    assert a.confidence == Confidence.HEURISTIC  # 改写必须标注「需人工润色」


def test_title_missing_derives_from_h1():
    p = _page(title=None, h1=["防滑登山鞋 男款"])
    pack = build_fixpack([p], [_issue("title.missing", Severity.CRITICAL, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field == "title"][0]
    assert "防滑登山鞋" in a.after
    assert a.confidence == Confidence.HEURISTIC


def test_site_suffix_detected_and_reused_in_draft():
    """多数页面都带「 - 品牌名」尾巴 → 缺 title 的新页面也沿用这个写法。"""
    pages = [
        _page(url="https://demo.test/a", title="登山鞋 - 山野品牌"),
        _page(url="https://demo.test/b", title="冲锋衣 - 山野品牌"),
        _page(url="https://demo.test/c", title="背包 - 山野品牌"),
        _page(url="https://demo.test/new", title=None, h1=["帐篷"]),
    ]
    issues = [
        _issue("title.missing", Severity.CRITICAL, "https://demo.test/new"),
    ]
    pack = build_fixpack(pages, issues, "demo.test")
    a = [x for x in pack.actions if x.field == "title"][0]
    assert a.after == "帐篷 - 山野品牌"


def test_meta_missing_drafted_from_text_within_budget():
    body = "这是一段足够长的产品介绍正文，用来说明这一页到底在解决什么问题。" * 4
    p = _page(meta_description=None, text=body)
    pack = build_fixpack([p], [_issue("meta.missing", Severity.HIGH, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field == "meta_description"][0]
    assert a.after
    assert len(a.after) <= 78  # 中文预算
    assert a.after in body.replace(" ", "") or a.after.endswith("…") or a.after.endswith("。")


def test_meta_missing_on_empty_page_goes_manual_not_fabricated():
    """正文抽不出来时不硬编 description——「无中生有」比沉默更糟。"""
    p = _page(meta_description=None, text="", word_count=0)
    pack = build_fixpack([p], [_issue("meta.missing", Severity.HIGH, p.url)], "demo.test")

    assert not [a for a in pack.actions if a.field == "meta_description"]
    assert any(i.code == "meta.missing" for i in pack.manual_review)
    assert any("转人工" in n for n in pack.notes)


def test_canonical_missing_is_deterministic_self_url():
    p = _page(canonical=None, final_url="https://demo.test/p?utm=1")
    pack = build_fixpack([p], [_issue("canonical.missing", Severity.MEDIUM, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field == "canonical"][0]
    assert a.confidence == Confidence.DETERMINISTIC
    assert a.after == "https://demo.test/p?utm=1"


def test_h1_multiple_keeps_first():
    p = _page(title="页面标题", h1=["主标题", "重复的主标题"])
    pack = build_fixpack([p], [_issue("h1.multiple", Severity.INFO, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field == "h1"][0]
    assert a.after == "主标题"
    assert a.confidence == Confidence.DETERMINISTIC


def test_img_alt_drafted_from_filename():
    p = _page(
        images=[ImageRef(src="https://cdn.demo.test/products/blue-hiking-shoes-2024.jpg")],
    )
    pack = build_fixpack([p], [_issue("img.alt.missing", Severity.MEDIUM, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field.startswith("img_alt")][0]
    assert a.after == "blue hiking shoes 2024"


def test_viewport_missing_constant():
    p = _page(viewport=None)
    pack = build_fixpack([p], [_issue("viewport.missing", Severity.HIGH, p.url)], "demo.test")

    a = [x for x in pack.actions if x.field == "viewport"][0]
    assert a.confidence == Confidence.DETERMINISTIC
    assert "width=device-width" in a.after


# --------------------------------------------------------------------------
# 站点级归因与配方
# --------------------------------------------------------------------------


def test_duplicate_title_maps_one_action_per_page():
    pages = [
        _page(url="https://demo.test/a", title="同一个标题", meta_description="x" * 30),
        _page(url="https://demo.test/b", title="同一个标题", meta_description="y" * 30),
    ]
    pack = build_fixpack(pages, [_issue("title.duplicate", Severity.HIGH)], "demo.test")

    acts = [a for a in pack.actions if a.code == "title.duplicate"]
    assert len(acts) == 2  # 一条处方对应一个页面，工单要能落到人头上
    assert {a.url for a in acts} == {"https://demo.test/a", "https://demo.test/b"}
    # 差异化因子优先用页面自己的 H1（正面证据），没有 H1 才退化到路径
    assert all(a.confidence == Confidence.HEURISTIC for a in acts)


def test_robots_missing_is_site_level_recipe():
    pack = build_fixpack([_page()], [_issue("robots.missing", Severity.MEDIUM)], "demo.test")

    a = [x for x in pack.actions if x.code == "robots.missing"][0]
    assert a.url is None  # 站点级
    assert a.confidence == Confidence.RECIPE
    assert "Sitemap: https://demo.test/sitemap.xml" in a.after


def test_soft404_goes_to_manual_review_with_fix_hint():
    issue = _issue("soft404", Severity.MEDIUM, "https://demo.test/thin",
                   fix_hint="确认这页是不是真软 404")
    pack = build_fixpack([_page()], [issue], "demo.test")

    assert not pack.actions
    assert pack.manual_review == [issue]
    assert pack.manual_review[0].fix_hint == "确认这页是不是真软 404"


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------


def test_markdown_render_contains_before_after_and_brand():
    p = _page(title="超长的中文标题" * 8, meta_description="x" * 30)
    pack = build_fixpack([p], [_issue("title.too_long", Severity.MEDIUM, p.url)], "demo.test")
    md = render_fixpack_markdown(pack, brand="某某网络")

    assert "某某网络" in md
    assert "改前" in md and "改后" in md
    assert "机器起草" in md  # 可信度分档必须出现，不能只在 JSON 里
    assert "SEO 整改工单 · demo.test" in md


def test_json_csv_diff_renderers():
    p = _page(title="超长的中文标题" * 8, meta_description="x" * 30)
    pack = build_fixpack([p], [_issue("title.too_long", Severity.MEDIUM, p.url)], "demo.test")

    payload = render_fixpack(pack, "json")
    assert '"actions"' in payload and "demo.test" in payload

    csv_text = render_fixpack_csv(pack)
    assert csv_text.splitlines()[0].startswith("url,field,code,confidence")
    assert "title.too_long" in csv_text

    diff = render_fixpack_diff(pack)
    assert diff.startswith("--- a/https://demo.test/")
    assert "+title:" in diff

    try:
        render_fixpack(pack, "pdf")
    except ValueError as exc:
        assert "未知的工单格式" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("未知格式必须报错，不能静默降级")


# --------------------------------------------------------------------------
# 与真实规则引擎的集成：处方覆盖的 code 与规则产出对得上
# --------------------------------------------------------------------------


def test_integration_with_real_rule_engine():
    """一页缺 title / meta / canonical 的真实 HTML → 跑真规则 → 开出处方。"""
    from seoclaw.audit.engine import run_audit

    html = (
        '<html><head></head><body><h1>防滑登山鞋</h1>'
        "<p>这是一段足够长的正文，介绍这双鞋的防滑性能与适用场景，"
        "足够长到能当 description 的素材。</p></body></html>"
    )
    page = extract_page("https://demo.test/shoes", html, final_url="https://demo.test/shoes")
    issues, _ctx = run_audit([page], "demo.test", [Market.BASE], {})

    pack = build_fixpack([page], issues, "demo.test")
    fields = {a.field for a in pack.actions}
    assert "title" in fields  # title.missing 的处方
    assert "meta_description" in fields  # meta.missing 的处方
    # 真实规则 code 必须能被处方层认领（否则规则变了处方层会静默漏掉）
    assert all(a.code for a in pack.actions)
