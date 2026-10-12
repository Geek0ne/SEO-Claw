"""Google 生态规则测试。

写这类规则最容易出的错是**误报**：一个看着对的启发式，套到真实站点上
就是几十条噪音，用户从此不再相信报告。所以本文件里「不触发」的用例
和「触发」的用例一样重要，每条规则都两头都测。

另外，Google 规则必须只在 market 包含 GOOGLE 时才跑——
用 `test_google_rules_not_loaded_for_base_market` 守住这条，
否则 BASE 站点的报告会里混进一堆不适用的告警。

用法：
    PYTHONPATH=../.deps:. python3 -m pytest tests/test_rules_google.py -q
"""

from __future__ import annotations


from seoclaw.audit.engine import run_audit
from seoclaw.extract import extract_page
from seoclaw.models import Market, Severity


# --------------------------------------------------------------------------
# 构造器：比 test_rules.py 的 html() 更自由，因为要控制 <html> 上的属性
# （lang 缺失、viewport 缺失都不是普通 head 标签能造出来的）
# --------------------------------------------------------------------------


def html(
    *,
    title: str | None = "示例页面 - 演示站",
    lang: str | None = "zh-CN",
    viewport: str | None = "width=device-width, initial-scale=1",
    description: str | None = "这是一个用于测试的页面描述，包含足够长度的文本内容。",
    h1: str | None = "示例页面",
    canonical: str | None = None,
    body: str = "<p>内容</p>",
    images: list[tuple[str, str | None]] | None = None,
    jsonld: str | None = None,
) -> str:
    """拼 HTML。lang/viewport 传 None 表示**故意不输出该属性**。"""
    head_attrs = "" if lang is None else f' lang="{lang}"'
    parts = ["<!DOCTYPE html>", f"<html{head_attrs}>", "<head>"]
    parts.append('<meta charset="utf-8">')
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if description is not None:
        parts.append(f'<meta name="description" content="{description}">')
    if viewport is not None:
        parts.append(f'<meta name="viewport" content="{viewport}">')
    if canonical:
        parts.append(f'<link rel="canonical" href="{canonical}">')
    if jsonld:
        parts.append(f'<script type="application/ld+json">{jsonld}</script>')
    parts.append("</head>")
    if h1 is not None:
        parts.append(f"<h1>{h1}</h1>")
    parts.append(body)
    for src, alt in images or []:
        alt_attr = "" if alt is None else f'alt="{alt}"'
        parts.append(f'<img src="{src}"{alt_attr}>')
    parts.append("</html>")
    return "\n".join(parts)


ZH_BODY = "<p>" + "这是一段足够长的中文正文内容，用来让字符统计有足够样本。" * 30 + "</p>"
EN_BODY = "<p>" + ("This is a sufficiently long English body paragraph with plenty of " * 5) + "</p>"


def audit_one(source: str, url: str = "https://demo.test/page", market=None):
    """跑一次审计，返回 (code -> severity 字典, issues 列表)。"""
    pages = [extract_page(url, source)]
    issues, _ = run_audit(pages, "demo.test", market or [Market.BASE, Market.GOOGLE])
    out: dict[str, Severity] = {}
    for issue in issues:
        prev = out.get(issue.code)
        if prev is None or issue.severity.rank < prev.rank:
            out[issue.code] = issue.severity
    return out, issues


def only(issues, code):
    return [i for i in issues if i.code == code]


# --------------------------------------------------------------------------
# 加载边界
# --------------------------------------------------------------------------


def test_google_rules_not_loaded_for_base_market():
    """只开 BASE 的站点不该看到 Google 告警——否则每个站都白挨一刀。"""
    bad = html(lang=None, viewport=None, body=ZH_BODY)
    codes, _ = audit_one(bad, market=[Market.BASE])
    assert "lang.missing" not in codes
    assert "viewport.missing" not in codes


def test_google_rules_loaded_for_google_market():
    bad = html(lang=None, viewport=None, body=ZH_BODY)
    codes, _ = audit_one(bad, market=[Market.BASE, Market.GOOGLE])
    assert "lang.missing" in codes
    assert "viewport.missing" in codes


# --------------------------------------------------------------------------
# lang.missing
# --------------------------------------------------------------------------


def test_lang_missing_fires():
    codes, _ = audit_one(html(lang=None))
    assert codes.get("lang.missing") is Severity.HIGH


def test_lang_missing_gives_usable_hint():
    """evidence 必须告诉用户「这里该填什么」，而不只是说「没填」。"""
    _, issues = audit_one(html(lang=None, body=ZH_BODY))
    ev = only(issues, "lang.missing")[0].evidence
    assert ev["html_lang_found"] is False
    assert ev["detected_from_text"] == "cjk", "中文正文应被识别出可用作 lang 提示"
    assert ev["content_sample"]


def test_lang_present_does_not_fire():
    codes, _ = audit_one(html(lang="zh-CN", body=ZH_BODY))
    assert "lang.missing" not in codes


def test_lang_empty_string_counts_as_missing():
    """<html lang=""> 是「写了但没填」，和缺失一样有害。"""
    codes, _ = audit_one(html(lang=""))
    assert "lang.missing" in codes


def test_lang_missing_not_reported_on_404():
    """404 页不该被收录，自然无所谓 lang。"""
    page = extract_page("https://demo.test/gone", html(lang=None), status_code=404)
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "lang.missing")


# --------------------------------------------------------------------------
# lang.not_html_lang
# --------------------------------------------------------------------------


def test_lang_mismatch_fires_when_latin_declared_but_cjk_content():
    """lang=en 但整页中文——典型的模板没跟着内容改。"""
    codes, _ = audit_one(html(lang="en", body=ZH_BODY))
    assert codes.get("lang.not_html_lang") is Severity.MEDIUM


def test_lang_mismatch_evidence_is_self_verifiable():
    """证据要带字符计数和正文样本，用户能自己核对，不用信工具。"""
    _, issues = audit_one(html(lang="en-US", body=ZH_BODY))
    ev = only(issues, "lang.not_html_lang")[0].evidence
    assert ev["html_lang"] == "en-US"
    assert ev["expected_script"] == "latin"
    assert ev["actual_script"] == "cjk"
    assert ev["cjk_chars"] > ev["latin_chars"]
    assert ev["sampled_chars"] == ev["cjk_chars"] + ev["latin_chars"]
    assert "这是一段" in ev["content_sample"]


def test_lang_mismatch_fires_when_cjk_declared_but_latin_content():
    codes, _ = audit_one(html(lang="zh-CN", body=EN_BODY))
    assert "lang.not_html_lang" in codes


def test_lang_matching_content_does_not_fire():
    codes, _ = audit_one(html(lang="en", body=EN_BODY))
    assert "lang.not_html_lang" not in codes


def test_lang_mismatch_skips_404():
    page = extract_page("https://demo.test/x", html(lang="en", body=ZH_BODY), status_code=404)
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "lang.not_html_lang")


def test_lang_mismatch_silent_on_tiny_sample():
    """样本只有几十个字符时，比例判断没有意义——短页面误报率极高。"""
    short = "<p>很短的说明文字</p>"
    page = extract_page("https://demo.test/s", html(lang="en", body=short))
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "lang.not_html_lang"), "短文本不应触发语言不匹配"


def test_lang_mismatch_silent_on_unknown_script_langs():
    """阿拉伯语/希伯来语等我们不做判断，工具得闭嘴而不是乱猜。"""
    ar = "<p>" + ("هذا نص عربي طويل لاختبار اللغة " * 30) + "</p>"
    page = extract_page("https://demo.test/ar", html(lang="ar", body=ar))
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "lang.not_html_lang")


def test_lang_mismatch_silent_on_mixed_content_page():
    """中英混排是合法落地页，比例不悬殊时不该报。

    ⚠️ 这里刻意用**中英数量相当**的样本，并把字符数断言出来。
    早先的样本每轮 25 个拉丁字符对 4 个汉字，拉丁确实占绝对多数，
    规则触发是**正确**的——错的是样本，不是规则。
    """
    mixed = "<p>" + ("中文内容更多的段落 text words here " * 30) + "</p>"
    page = extract_page("https://demo.test/m", html(lang="zh-CN", body=mixed))

    # 先证明这个样本确实「中英均衡」，否则本测试的「不触发」毫无意义
    from seoclaw.audit.rules.google import _script_counts
    cjk, latin = _script_counts(page.text)
    assert cjk > 0 and latin > 0
    assert latin < cjk * 2, f"样本应中英均衡，实际 cjk={cjk} latin={latin}"

    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "lang.not_html_lang")


def test_lang_mismatch_fires_on_latin_heavy_page():
    """反过来：lang 声明中文、正文却以英文为主，属于真问题，必须报。"""
    latin_heavy = "<p>" + ("English dominates this page with only 少数字 Chinese here " * 20) + "</p>"
    page = extract_page("https://demo.test/lh", html(lang="zh-CN", body=latin_heavy))
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert only(issues, "lang.not_html_lang")

# --------------------------------------------------------------------------
# viewport.missing
# --------------------------------------------------------------------------


def test_viewport_missing_fires():
    codes, _ = audit_one(html(viewport=None))
    assert codes.get("viewport.missing") is Severity.HIGH


def test_viewport_present_does_not_fire():
    codes, _ = audit_one(html(viewport="width=device-width, initial-scale=1"))
    assert "viewport.missing" not in codes


def test_viewport_missing_not_reported_on_404():
    page = extract_page("https://demo.test/gone", html(viewport=None), status_code=404)
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "viewport.missing")


# --------------------------------------------------------------------------
# viewport.not_responsive
# --------------------------------------------------------------------------


def test_viewport_without_device_width_fires():
    """固定 980px 宽度是 2014 年的写法，现在会让整页缩成蚂蚁。"""
    codes, _ = audit_one(html(viewport="width=980, initial-scale=1"))
    assert codes.get("viewport.not_responsive") is Severity.MEDIUM


def test_viewport_not_responsive_is_flagged_as_maybe_intentional():
    """可能有合理解释 → evidence 必须给 verdict 让用户自己判断。"""
    _, issues = audit_one(html(viewport="width=980"))
    ev = only(issues, "viewport.not_responsive")[0].evidence
    assert ev["verdict"] == "possibly_intentional"
    assert ev["viewport"] == "width=980"


def test_viewport_device_width_does_not_fire():
    codes, _ = audit_one(html(viewport="width=device-width, initial-scale=1"))
    assert "viewport.not_responsive" not in codes


def test_viewport_absent_is_not_double_reported():
    """viewport 完全没有时只报缺失，不该再报一次「没用 device-width」。"""
    _, issues = audit_one(html(viewport=None))
    assert not only(issues, "viewport.not_responsive")


def test_user_scalable_no_is_surfaced_in_evidence():
    """禁缩放是无障碍问题。即便 device-width 写对了也不能放过。"""
    _, issues = audit_one(html(viewport="width=device-width, user-scalable=no"))
    ev = only(issues, "viewport.not_responsive")[0].evidence
    assert ev["has_user_scalable_no"] is True
    assert ev["has_device_width"] is True
    assert ev["problems"] == ["user_scalable_no"]


def test_user_scalable_yes_does_not_fire():
    """允许缩放 + device-width 是标准配置，不该报。"""
    codes, _ = audit_one(html(viewport="width=device-width, initial-scale=1, user-scalable=yes"))
    assert "viewport.not_responsive" not in codes


def test_viewport_fixed_width_reports_missing_device_width():
    _, issues = audit_one(html(viewport="width=980, initial-scale=1"))
    ev = only(issues, "viewport.not_responsive")[0].evidence
    assert ev["has_device_width"] is False
    assert ev["problems"] == ["missing_device_width"]


# --------------------------------------------------------------------------
# title.pixel_overflow
# --------------------------------------------------------------------------


def test_title_pixel_overflow_fires_on_long_latin_title():
    """62 个小写字母 ≈ 510px 还没超，85 个必然超。"""
    codes, _ = audit_one(html(title="a" * 85, lang="en"))
    assert codes.get("title.pixel_overflow") is Severity.MEDIUM


def test_title_pixel_overflow_evidence_numbers():
    _, issues = audit_one(html(title="a" * 85, lang="en"))
    ev = only(issues, "title.pixel_overflow")[0].evidence
    assert ev["title_length"] == 85
    assert ev["estimated_px"] > ev["threshold_px"] == 580
    assert round(ev["estimated_px"] - ev["threshold_px"], 1) == ev["overflow_px"]
    assert ev["latin_chars"] == 85
    assert ev["verdict"] == "likely_truncated"


def test_short_title_does_not_fire():
    codes, _ = audit_one(html(title="防水登山鞋 男款 - 品牌名"))
    assert "title.pixel_overflow" not in codes


def test_cjk_title_under_30_chars_does_not_fire():
    """30 个汉字 ≈ 480px，在安全区内——字符数看着危险，像素没超。"""
    codes, _ = audit_one(html(title="标" * 30))
    assert "title.pixel_overflow" not in codes


def test_cjk_title_over_threshold_fires():
    """37 个汉字 ≈ 592px，越界。"""
    codes, _ = audit_one(html(title="标" * 37))
    assert "title.pixel_overflow" in codes


def test_title_pixel_overflow_not_reported_without_title():
    """没有 title 是 title.missing 的活，不该在这再报一次。"""
    codes, _ = audit_one(html(title=None, lang="en"))
    assert "title.pixel_overflow" not in codes


def test_title_pixel_overflow_not_reported_on_404():
    page = extract_page("https://demo.test/g", html(title="a" * 90, lang="en"), status_code=404)
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE])
    assert not only(issues, "title.pixel_overflow")


# --------------------------------------------------------------------------
# 整体：合规页面零告警
# --------------------------------------------------------------------------


def test_google_compliant_page_has_no_google_issues():
    """一个 lang、viewport、title 都规矩的页面，不该产生任何 Google 规则告警。"""
    good = html(
        title="防水登山鞋 男款防水防滑耐磨 - 演示品牌",
        lang="zh-CN",
        viewport="width=device-width, initial-scale=1",
        canonical="https://demo.test/ok",
        h1="防水登山鞋",
        images=[("/a.jpg", "黑色防水登山鞋侧视图")],
        jsonld='{"@context":"https://schema.org","@type":"Product","name":"防水登山鞋"}',
        body="<p>" + "登山鞋选购指南，覆盖防水等级、鞋底材质与适用场景。" * 40 + "</p>",
    )
    codes, _ = audit_one(good, url="https://demo.test/ok")
    google_codes = {
        c for c in codes
        if c in {"lang.missing", "lang.not_html_lang", "viewport.missing",
                 "viewport.not_responsive", "title.pixel_overflow"}
    }
    assert not google_codes, f"合规页面不该有 Google 告警，实际：{google_codes}"


def test_google_issues_carry_google_market_tag():
    """market 字段必须标成 google，前端才能按站点市场过滤。"""
    _, issues = audit_one(html(lang=None, viewport=None, body=ZH_BODY))
    google_issues = [i for i in issues if i.code.startswith(("lang.", "viewport."))]
    assert google_issues
    assert all(i.market is Market.GOOGLE for i in google_issues)


def test_every_google_issue_carries_evidence():
    """本包的核心约定：没有证据的结论不许输出。"""
    _, issues = audit_one(
        html(lang="en", viewport="width=980", title="a" * 90, body=ZH_BODY)
    )
    google_codes = {"lang.not_html_lang", "viewport.not_responsive", "title.pixel_overflow"}
    fired = [i for i in issues if i.code in google_codes]
    assert len(fired) == 3, f"预期三条都触发，实际：{[i.code for i in fired]}"
    for issue in fired:
        assert issue.evidence, f"{issue.code} 缺少 evidence"
        assert issue.evidence.get("verdict"), f"{issue.code} 缺少 verdict 供用户判断"
        assert issue.evidence.get("verdict_explain"), f"{issue.code} 缺少 verdict 说明"
