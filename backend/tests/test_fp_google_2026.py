"""
google 包 2026 回源核对的 12 条真误报回归测试。

背景
----
107 站真实扫描后，核对器逐条回访目标 URL 拿真实内容比对，判出 google 包
有 12 条**真误报**（规则说有问题、实际没问题）。本文件把每一类根因钉死，
每个用例都成对：一条「样本必须闭嘴」+ 一条「反向用例仍要触发」。

反向用例是这份文件存在的理由。上一轮我修 canonical 误报时，把误报降级成
INFO 就算「修好了」——规则照样产出条目、照样扣分，严格准确率反而从 6% 掉
到 0%。所以这里的断言不是「没报错」，而是**规则在该触发时仍产出条目**，
防止把规则改成永远沉默。

样本一律用扫描 JSON 里的原始 evidence（html_lang / declared_hreflang /
self_url），不改写成比真实情况更温和的形式。
"""

from __future__ import annotations

from seoclaw.audit.engine import run_audit
from seoclaw.extract import extract_page
from seoclaw.models import Market, Page, Severity
from seoclaw.audit.rules.google.i18n import HreflangMismatchesLang, HreflangSelfMissing
from seoclaw.audit.rules.google import TitlePixelOverflow


def page(**kw) -> Page:
    """直接构造 Page：这些用例关心的是规则的判定，不是提取层。"""
    data = {"url": "https://demo.test/p", "status_code": 200}
    data.update(kw)
    return Page(**data)


def codes(page_obj: Page) -> list[str]:
    issues, _ = run_audit([page_obj], "demo.test", [Market.GOOGLE])
    return [i.code for i in issues]


def hits(rule, page_obj: Page) -> list[str]:
    return [i.code for i in rule.check(page_obj, None)]


def html(head_extra: str = "", *, lang: str = "en", title: str | None = "x", body: str = "<p>c</p>") -> str:
    t = f"<title>{title}</title>" if title else ""
    return f'<html lang="{lang}"><head>{t}{head_extra}</head><body>{body}</body></html>'


def audit_html(source: str, url: str = "https://demo.test/p") -> list[str]:
    p = extract_page(url, source, final_url=url)
    return codes(p)


# --------------------------------------------------------------------------
# hreflang.inconsistent_with_lang —— 误报 6 → 0
#
# 根因（单一原因，6 条同源）：集合里有 x-default、且 x-default 指回本页自己
# 时，本页语言已经被兜底覆盖，**不需要再显式声明一次自己**。原规则把 x-default
# 从 declared 里剔掉之后（那一步是对的），却仍然拿「own lang 不在 declared」
# 判不一致——等于一边承认 x-default 是特殊兜底，一边又要本站自己重复声明。
#
#   - medlineplus.gov  lang=en，集合 ["x-default"]（x-default→本页）
#   - www.cloudflare.com lang=en，集合 10 种非英语言 + x-default（→本页），
#     语言码小写 de-de/es-es…、区域码 pt-br=巴葡 / zh-cn=简中 / zh-tw=繁中，
#     原规则只取 "-" 前一段比对，这些写法全部与 html lang 无关但不影响结论
# --------------------------------------------------------------------------

MEDLINEPLUS = ("https://medlineplus.gov/", "en", [("x-default", "https://medlineplus.gov/")])

CLOUDFLARE_LANGS = [
    ("de-de", "/de-de/"), ("es-es", "/es-es/"), ("fr-fr", "/fr-fr/"),
    ("it-it", "/it-it/"), ("ja-jp", "/ja-jp/"), ("ko-kr", "/ko-kr/"),
    ("pt-br", "/pt-br/"), ("x-default", "/"), ("zh-cn", "/zh-cn/"),
    ("zh-tw", "/zh-tw/"),
]


def test_inconsistent_silent_medlineplus_x_default_only():
    """样本一：只有 x-default 兜底，不算不一致。"""
    url, lang, hl = MEDLINEPLUS
    p = page(url=url, final_url=url, lang=lang,
             hreflang=[(c, u if u.startswith("http") else url.rstrip("/") + u) for c, u in hl])
    assert hits(HreflangMismatchesLang(), p) == []


def test_inconsistent_silent_cloudflare_english_homepage():
    """样本二/三：英文页 + 10 种非英语言 + x-default 指回自己。"""
    url = "https://www.cloudflare.com/"
    p = page(url=url, final_url=url, lang="en",
             hreflang=[(c, url.rstrip("/") + u) for c, u in CLOUDFLARE_LANGS])
    assert hits(HreflangMismatchesLang(), p) == []


def test_inconsistent_still_fires_when_x_default_points_elsewhere():
    """反向：x-default 指向**别的**页时，本页语言仍是真的没进集合，必须报。"""
    p = page(url="https://a.test/en/", final_url="https://a.test/en/", lang="en",
             hreflang=[("x-default", "https://a.test/"),
                       ("de", "https://a.test/de/"), ("fr", "https://a.test/fr/")])
    assert "hreflang.inconsistent_with_lang" in hits(HreflangMismatchesLang(), p)


def test_inconsistent_still_fires_without_x_default():
    """反向：没有 x-default 兜底时，lang 不在集合里就是真不一致。"""
    p = page(url="https://a.test/en/", final_url="https://a.test/en/", lang="en",
             hreflang=[("de", "https://a.test/de/"), ("fr", "https://a.test/fr/")])
    assert "hreflang.inconsistent_with_lang" in hits(HreflangMismatchesLang(), p)


def test_inconsistent_still_fires_for_single_declared_language():
    """反向：只声明了一种其它语言，x-default 也没有 → 仍要报。"""
    p = page(url="https://a.test/en/", final_url="https://a.test/en/", lang="en",
             hreflang=[("zh-CN", "https://a.test/zh/")])
    assert "hreflang.inconsistent_with_lang" in hits(HreflangMismatchesLang(), p)


def test_inconsistent_still_fires_on_declaration_mismatch_in_declared_set():
    """反向：html lang 是 en，集合里只有 x-default 且指回本页 → 这是合规写法；
    但 html lang 是 en 而 x-default 指回本页、集合里有其它语言时仍应放行；
    若 html lang 指向一种**集合里自称有、实际没声明**的语言则要报。"""
    p = page(url="https://a.test/ja/", final_url="https://a.test/ja/", lang="ja",
             hreflang=[("x-default", "https://a.test/"), ("en", "https://a.test/en/")])
    assert "hreflang.inconsistent_with_lang" in hits(HreflangMismatchesLang(), p)


def test_inconsistent_region_codes_still_matched_when_present():
    """反向：区域码写法只要出现就不该被漏判——zh-CN 页配 zh-cn 声明仍算一致。"""
    p = page(url="https://a.test/", final_url="https://a.test/", lang="zh-CN",
             hreflang=[("zh-cn", "https://a.test/zh-cn/"), ("en", "https://a.test/en/")])
    assert hits(HreflangMismatchesLang(), p) == []


def test_inconsistent_no_hreflang_stays_silent():
    """没有 hreflang 数据时本就闭嘴（不是靠 lang 推断）。"""
    p = page(url="https://a.test/", final_url="https://a.test/", lang="en")
    assert hits(HreflangMismatchesLang(), p) == []


# --------------------------------------------------------------------------
# hreflang.self_reference_missing —— 误报 4 → 0
#
# 三个根因，各占一部分：
#   A. 分页/CMS 视图参数（2 条：?page=4、?page_id=36859）——这些参数标识的是
#      同一篇文档的一个位置，hreflang 指向不带参数的主文档 URL 是正确写法。
#   B. 首页别名（1 条：edx 的 / 与 /homepage）——与 base 包 canonical 的
#      index_or_home_alias 同一惯例（https://www.edx.org/homepage 是实跑取到的）。
#   C. 有 canonical 的页面应以 canonical 为身份比对（Google 要求 hreflang 指向
#      canonical URL），否则在有 canonical 的站点上会稳定地比不相等。
# --------------------------------------------------------------------------

DISCOURSE_TOPIC = "https://meta.discourse.org/t/voice-discord-style-voice-and-video-rooms-now-bundled-with-discourse/411337"


def test_self_ref_silent_discourse_paginated_page4():
    """样本一：?page=4 论坛分页页，自引用 href 指主文档。"""
    p = page(url=f"{DISCOURSE_TOPIC}?page=4", final_url=f"{DISCOURSE_TOPIC}?page=4", lang="zh-CN",
             hreflang=[("x-default", DISCOURSE_TOPIC), ("en", DISCOURSE_TOPIC),
                       ("zh-CN", DISCOURSE_TOPIC), ("es", DISCOURSE_TOPIC),
                       ("de", DISCOURSE_TOPIC), ("pt-BR", DISCOURSE_TOPIC)])
    assert hits(HreflangSelfMissing(), p) == []


def test_self_ref_silent_pagerduty_query_view():
    """样本二：?page_id=36859 的 CMS 视图，集合里有 en 且指向干净首页。"""
    p = page(url="https://www.pagerduty.com/?page_id=36859",
             final_url="https://www.pagerduty.com/?page_id=36859", lang="en",
             hreflang=[("x-default", "https://www.pagerduty.com/"),
                       ("en", "https://www.pagerduty.com/"),
                       ("fr", "https://www.pagerduty.com/fr/"),
                       ("es", "https://www.pagerduty.com/es/"),
                       ("pt", "https://www.pagerduty.com/pt/"),
                       ("de", "https://www.pagerduty.com/de/")])
    assert hits(HreflangSelfMissing(), p) == []


def test_self_ref_silent_edx_homepage_alias():
    """样本三：实跑 https://www.edx.org/ 得到 en → /homepage、es → /es/homepage。"""
    p = page(url="https://www.edx.org/", final_url="https://www.edx.org/", lang="en",
             hreflang=[("es", "https://www.edx.org/es/homepage"),
                       ("en", "https://www.edx.org/homepage")])
    assert hits(HreflangSelfMissing(), p) == []


def test_self_ref_uses_canonical_as_identity():
    """根因 C：页面 canonical 存在时，hreflang 指向 canonical 才是 Google 要求的写法。"""
    p = page(url="https://a.test/p?utm_source=x", final_url="https://a.test/p?utm_source=x",
             lang="en", canonical="https://a.test/p",
             hreflang=[("en", "https://a.test/p"), ("de", "https://a.test/p?lang=de")])
    assert hits(HreflangSelfMissing(), p) == []


def test_self_ref_still_fires_when_own_language_absent():
    """反向：/zh/ 页面的集合里没有指向 /zh/ 的 zh-CN 条目 → 真缺自引用。"""
    p = page(url="https://a.test/zh/", final_url="https://a.test/zh/", lang="zh-CN",
             hreflang=[("en", "https://a.test/en/"), ("de", "https://a.test/de/")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), p)


def test_self_ref_still_fires_when_self_entry_has_wrong_language():
    """反向：有指向本页的条目，但语言是 en 而本页是 fr → 仍要报。"""
    p = page(url="https://a.test/fr/", final_url="https://a.test/fr/", lang="fr",
             hreflang=[("en", "https://a.test/fr/"), ("de", "https://a.test/de/")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), p)


def test_self_ref_still_fires_for_content_query_param():
    """反向：?sort=price 可能是真的另一份内容，不在视图参数白名单里，不能放行
    （放行会造成漏报，漏报比误报更坏）。"""
    p = page(url="https://a.test/p?sort=price", final_url="https://a.test/p?sort=price", lang="en",
             hreflang=[("en", "https://a.test/p"), ("de", "https://a.test/de/p")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), p)


def test_self_ref_still_fires_for_page_id_alike_content_param():
    """反向：?id=123 这类内容参数同样不能被当成视图参数。"""
    p = page(url="https://a.test/p?id=123", final_url="https://a.test/p?id=123", lang="en",
             hreflang=[("en", "https://a.test/p"), ("de", "https://a.test/de/p")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), p)


def test_self_ref_still_fires_when_set_points_to_other_pages_only():
    """反向：集合里全是别的页面，指向本页的只有 x-default 指向别处。"""
    p = page(url="https://a.test/en/", final_url="https://a.test/en/", lang="en",
             hreflang=[("x-default", "https://a.test/"), ("de", "https://a.test/de/")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), p)


def test_self_ref_home_alias_does_not_fold_across_hosts():
    """反向：别名折叠只在同 host 内生效，且按整段匹配（/myhomepage 不折叠）。"""
    other_host = page(url="https://a.test/x/", final_url="https://a.test/x/", lang="en",
                      hreflang=[("en", "https://b.test/x/home"), ("de", "https://a.test/de/x")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), other_host)
    # /myhomepage 不是别名段：只剥最后**一整段**别名，不能把 /my + homepage 拼起来折叠
    not_alias = page(url="https://a.test/myhomepage/", final_url="https://a.test/myhomepage/", lang="en",
                     hreflang=[("en", "https://a.test/homepage"), ("de", "https://a.test/de/x")])
    assert "hreflang.self_reference_missing" in hits(HreflangSelfMissing(), not_alias)
    # 但同 host 下的结尾别名（/x/ 与 /x/home）确实折叠，否则 edx 样本会重新误报
    same_host = page(url="https://a.test/x/", final_url="https://a.test/x/", lang="en",
                     hreflang=[("en", "https://a.test/x/home"), ("de", "https://a.test/de/x")])
    assert hits(HreflangSelfMissing(), same_host) == []


def test_self_ref_no_lang_stays_silent():
    """没有 lang 时无从判断自引用该写什么，交给 lang.missing。"""
    p = page(url="https://a.test/p/", final_url="https://a.test/p/",
             hreflang=[("de", "https://a.test/de/")])
    assert hits(HreflangSelfMissing(), p) == []


# --------------------------------------------------------------------------
# title.pixel_overflow —— 误报 2 → 1（见文件末尾的诚实说明）
#
# 根因（golf.com 那条）：规则的像素值是**估算**，不是测量。估算表自己声明误差
# ±10%，而该样本只超出 3.9px（583.9 vs 580.0，占 0.7%）——结论完全落在估算
# 误差以内。修法不是改阈值，而是只在「误差带下界仍然越界」时才报。
#
# 顺带修了估算器本身的两个真实缺陷（真实样本：discourse 中文标题）：
#   - emoji 🎙(U+1F399) 原先按标点 5.5px 算，实际近全角 16px；
#   - 中文弯引号 “” 原先按窄字符 4.5px 算，在 CJK 字体里是全角 16px。
# 这两项让估算更准 —— 注意方向是**把估算值调高**，只会让规则更容易触发。
# --------------------------------------------------------------------------

GOLF_TITLE = ("Tom Brady is struggling mightily in The Match, and Twitter is "
              "roasting him | GOLF.com")


def test_pixel_overflow_silent_within_estimate_error_band():
    """样本一 golf.com：估 583.9px、超 3.9px，落在 ±10% 估算误差内 → 闭嘴。"""
    assert list(TitlePixelOverflow().check(page(url="https://golf.com/x", title=GOLF_TITLE), None)) == []


def test_pixel_overflow_error_band_is_not_a_threshold_bump():
    """沉默的是「误差带内」而不是「更大阈值」：一个明确大幅越界的标题仍要报。"""
    p = page(url="https://golf.com/x", title="a" * 200)
    assert "title.pixel_overflow" in hits(TitlePixelOverflow(), p)


def test_pixel_overflow_still_fires_just_outside_band():
    """边界方向：误差带按「字宽随字体而变的字符占比」缩放。

    37 个汉字 = 592px，字宽是定宽的 1em → 误差带 0 → 592 确实是越界，必须报。
    （这条与 test_rules_google.py 里的既有断言一致，不能为了迁就某个样本
      把定宽 CJK 的确定性也抹掉。）
    """
    assert "title.pixel_overflow" in hits(TitlePixelOverflow(), page(url="https://a.test/", title="标" * 37))


def test_pixel_overflow_error_band_scales_with_uncertainty():
    """全是拉丁字母的标题误差带最大；汉字定宽所以误差带为 0。"""
    from seoclaw.audit.rules.google import _estimate_title_px

    assert _estimate_title_px("标" * 10)["variable_share"] == 0.0
    assert _estimate_title_px("abc def")["variable_share"] == 1.0


def test_pixel_overflow_evidence_reports_uncertainty_band():
    """触发的条目必须在 evidence 里给出误差带，供人工复核。"""
    src = html(title="a" * 120, lang="en")
    p = extract_page("https://demo.test/p", src, final_url="https://demo.test/p")
    issues, _ = run_audit([p], "demo.test", [Market.GOOGLE])
    ev = next(i for i in issues if i.code == "title.pixel_overflow").evidence
    assert ev["estimate_error_band"] == 0.10  # 纯拉丁 → 最大误差带
    assert ev["low_bound_px"] < ev["estimated_px"]
    assert ev["emoji_chars"] == 0


def test_estimator_counts_emoji_as_full_width():
    """估算器缺陷修复：emoji 按 1em 而不是标点宽度计入。"""
    from seoclaw.audit.rules.google import _estimate_title_px

    plain = _estimate_title_px("ab")
    with_emoji = _estimate_title_px("a\U0001F399b")
    assert round(with_emoji["estimated_px"] - plain["estimated_px"], 1) == 16.0
    assert with_emoji["emoji"] == 1


def test_estimator_counts_cjk_curly_quotes_as_full_width():
    """估算器缺陷修复：中文标题里的 “” 是全角；英文标题里的 ' 仍是窄的。"""
    from seoclaw.audit.rules.google import _estimate_title_px

    cjk_q = _estimate_title_px("标“字”")
    assert round(cjk_q["estimated_px"] - _estimate_title_px("标字")["estimated_px"], 1) == 32.0
    ascii_q = _estimate_title_px("ab'c")
    assert round(ascii_q["estimated_px"] - _estimate_title_px("abc")["estimated_px"], 1) == 4.5


def test_pixel_overflow_severity_and_reverse_cases():
    """触发时仍是 MEDIUM 的实质条目，不是降级噪音。"""
    p = extract_page("https://demo.test/p", html(title="a" * 120, lang="en"),
                     final_url="https://demo.test/p")
    issues, _ = run_audit([p], "demo.test", [Market.GOOGLE])
    issue = next(i for i in issues if i.code == "title.pixel_overflow")
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence["verdict"] == "likely_truncated"
    # 短标题与安全区内标题依然闭嘴
    assert "title.pixel_overflow" not in audit_html(html(title="防水登山鞋 男款 - 品牌名"))
    assert "title.pixel_overflow" not in audit_html(html(title="标" * 30))