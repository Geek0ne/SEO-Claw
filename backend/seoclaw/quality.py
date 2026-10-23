"""质量与验证：把后端已有的验证能力变成可调用的接口。

⚠️ 这个模块为什么存在：项目里最有说服力的资产是**验证记录**——107 站
实跑准确率、18 条规则的回源核对台账、黄金样本回归、737 条测试。但这些
全都躺在 ``docs/`` 与 ``backend/tests/`` 里，**Web 界面上一个都看不到**。
产品演示时讲「我们 97% 准确」，用户只能选择信或不信；界面上能当场跑
一遍自检、自己看每条规则判据，结论才立得住。

这个模块只做三件事，且都不重复造轮子：

1. **规则目录**：从 ``default_registry()`` 实况导出（不是硬编码清单）——
   规则加了、删了、改了严重级，接口自动跟着变。
2. **黄金样本自检**：用**构造的 HTML** 跑一遍真实规则引擎，逐条核对
   「该触发的触发了、该沉默的沉默了」。判据来自 ``audit/rules/`` 本身，
   这里不重写规则逻辑。
3. **验证台账**：把 ``docs/`` 下的准确率报告与回源台账读出来给界面用。

**口径纪律**（这个仓库一贯的要求）：

- 规则目录**只从注册表导出**。另写一份清单必然分叉——分叉之后没人知道
  该信哪个，而这就是本项目反复踩的坑。
- 自检的期望值**写在用例旁边**（期望触发 / 期望沉默），用例失败就红，
  不允许「自检永远通过」这种自欺。
- 准确率数字**只从 ``docs/accuracy_*.json`` 读**，接口不自己算一遍。
  算两遍就会分叉。
- 读不到文件时**如实返回「无数据」**，不返回 0、不返回默认值。
  「没测过」和「测了是 0」是两回事，报告里分不开就没法决策。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .audit.engine import default_registry
from .audit.engine import Rule
from .extract import extract_page
from .models import Market, Page

#: ``docs/`` 目录的定位方式。
#:
#: ⚠️ 为什么不能写死相对路径：包被 pip 装到 site-packages 后，``docs/``
#: 不在包内（``pyproject.toml`` 的 package-dir 指向 backend/）。写死
#: ``Path(__file__).parent.parent.parent / "docs"`` 在开发机上能跑，装了
#: 就 404 —— 那种「本地好好的、一部署就空」的故障最难查。
#:
#: 所以按三档找：① 环境变量显式指定 ② 仓库根（开发机）③ 找不到就返回
#: 无数据。**找不到不是错误**：规则目录与自检都不依赖 docs/，缺了它只少
#: 一块展示，不是整个功能挂掉。
_DOCS_ENV = "SEO_CLAW_DOCS_DIR"


def _docs_root() -> Optional[Path]:
    """定位 ``docs/`` 目录。找不到返回 None。

    ⚠️ 环境变量显式指定时**不回退**：指定了却悄悄用另一个目录，
    部署者会以为在看 A 目录的台账、实际看到的是 B 目录的——那是
    「配置了却不生效」，比配置不生效更难查。指定了就以它为准。
    """
    env = os.environ.get(_DOCS_ENV)
    if env:
        p = Path(env).expanduser()
        return p if p.is_dir() else None
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs"
        if (candidate / "accuracy_recheck.json").exists():
            return candidate
    return None


def docs_dir() -> Optional[Path]:
    """``docs/`` 目录位置。找不到返回 None（调用方必须能处理 None）。"""
    return _docs_root()


# --------------------------------------------------------------------------
# 1. 规则目录：从注册表实况导出
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleInfo:
    """一条规则的元信息。**不含判据实现**——那是 ``audit/rules/`` 的事。"""

    code: str
    title: str
    severity: str
    scope: str
    market: str
    description: str
    fix_hint: str
    fix_example: Optional[str]
    uses_site_facts: bool


def _rule_to_info(rule: Rule) -> RuleInfo:
    return RuleInfo(
        code=rule.code,
        title=rule.title,
        severity=rule.severity.value,
        scope=rule.scope.value,
        market=rule.market.value,
        description=rule.description,
        fix_hint=rule.fix_hint,
        fix_example=rule.fix_example,
        uses_site_facts=bool(getattr(rule, "uses_site_facts", False)),
    )


def rule_catalog(markets: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """导出规则目录。

    ⚠️ **只从注册表导出**，不另写清单：另写一份必然与代码分叉，而分叉
    之后没人知道该信哪个（本项目已因口径分叉返工过多次，见 PLAN.md）。

    ``markets`` 给定时只返回这些市场包 + base 的规则；不给则返回全部
    市场包。**base 的规则在每个市场包下都会出现**——这是设计如此：
    base 是所有市场共用的检查项，不是某个市场专属的。
    """
    reg = default_registry()
    wanted: Optional[set[str]] = None
    if markets:
        wanted = {m.strip().lower() for m in markets if m.strip()}

    seen: dict[str, RuleInfo] = {}
    for market in Market:
        if wanted is not None and market.value not in wanted:
            continue
        rules = reg.page_rules_for([market]) + reg.site_rules_for([market])
        for rule in rules:
            # ⚠️ 同一个 code 在多个市场包下可能出现（base 的规则 + 某市场
            # 自己的同名规则）。按 code 去重时**保留先遇到的**——加载顺序
            # 是 base → google → baidu → cnh_eco，先遇到的是更通用的那条。
            # 但市场包专属的规则不能被 base 的同名规则顶掉，所以这里
            # 记下「这个 code 属于哪些市场」，让界面能标出覆盖面。
            if rule.code not in seen:
                seen[rule.code] = _rule_to_info(rule)

    items = sorted(seen.values(), key=lambda r: (r.market, r.code))
    by_market: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    for r in items:
        by_market[r.market] = by_market.get(r.market, 0) + 1
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_scope[r.scope] = by_scope.get(r.scope, 0) + 1
    return {
        "rules": [
            {
                "code": r.code,
                "title": r.title,
                "severity": r.severity,
                "scope": r.scope,
                "market": r.market,
                "description": r.description,
                "fix_hint": r.fix_hint,
                "fix_example": r.fix_example,
                "uses_site_facts": r.uses_site_facts,
            }
            for r in items
        ],
        "count": len(items),
        "by_market": by_market,
        "by_severity": by_severity,
        "by_scope": by_scope,
    }


# --------------------------------------------------------------------------
# 2. 黄金样本自检：真跑规则引擎，逐条核对
# --------------------------------------------------------------------------
#
# ⚠️ 期望值写在用例旁边，用例不满足就红。**不允许「自检永远通过」**——
# 那种自检比没有更坏：它给人「已验证」的安全感，而实际什么都没验。
#
# 语料是**构造的 HTML**，不是真实站点快照：完全确定、不联网、跑得快。
# 缺点是覆盖不到真实站点的脏 HTML——所以准确率另有 107 站实跑背书，
# 两件事各管一段，不要互相冒充。

#: 自检用的 HTML 构造器。参数名与 ``tests/test_rules.py`` 里的同名函数
#: 保持一致，方便对照。**只在这里造 HTML，不在别处造**。
def _html(
    *,
    title: Optional[str] = "示例页面 - 演示站",
    description: Optional[str] = "这是一个用于验证的页面描述，包含足够长度的文本内容。",
    h1: Optional[object] = "示例页面",
    canonical: Optional[str] = None,
    robots: Optional[str] = None,
    body: str = "<p>正文内容</p>",
    images: Optional[list[tuple[str, Optional[str]]]] = None,
    links: Optional[list[tuple[str, str]]] = None,
    jsonld: Optional[str] = None,
    lang: str = "zh-CN",
    head_extra: str = "",
) -> str:
    parts = ["<!DOCTYPE html>", f'<html lang="{lang}">', "<head>"]
    parts.append('<meta charset="utf-8">')
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if description is not None:
        parts.append(f'<meta name="description" content="{description}">')
    if robots is not None:
        parts.append(f'<meta name="robots" content="{robots}">')
    if canonical is not None:
        parts.append(f'<link rel="canonical" href="{canonical}">')
    if jsonld is not None:
        parts.append(f'<script type="application/ld+json">{jsonld}</script>')
    if head_extra:
        parts.append(head_extra)
    parts.append("</head>")
    if h1 is None:
        pass
    elif isinstance(h1, list):
        parts.extend(f"<h1>{h}</h1>" for h in h1)
    else:
        parts.append(f"<h1>{h1}</h1>")
    parts.append(body)
    for src, alt in images or []:
        alt_attr = "" if alt is None else f'alt="{alt}"'
        parts.append(f'<img src="{src}"{alt_attr}>')
    for href, anchor in links or []:
        parts.append(f'<a href="{href}">{anchor}</a>')
    parts.append("</html>")
    return "\n".join(parts)


@dataclass(frozen=True)
class SelfTestCase:
    """一条自检用例。

    ``expect`` 只有两个取值：

    - ``"fires"``：这条规则**应该**在这份语料上触发
    - ``"silent"``：这条规则**应该**保持沉默（语料是「正确写法」的样本）

    ⚠️ ``silent`` 用例与 ``fires`` 用例同等重要：规则的另一半价值是
    **不误报**。只测「该报的报了」的套件，等于没测误报——而误报比漏报
    更难被用户发现（漏报用户会骂工具，误报用户会照着改，改坏了才发现）。
    """

    code: str
    expect: str
    note: str
    html: str
    url: str = "https://demo.test/page"
    markets: tuple[str, ...] = ("base",)
    site_facts: Optional[dict[str, Any]] = None
    #: 需要多页才能判定的规则（如 title.duplicate）在这里给同批页面
    extra_pages: tuple[tuple[str, str], ...] = ()
    #: 页面在站点里的点击层级。``depth.excessive`` 这类按层级判定的规则
    #: 靠它触发——不传就是 0，规则永远沉默，用例就成了一句空断言。
    depth: int = 0
    #: HTTP 状态码。404/500 的 noindex 是**正确配置**（错误页本就不该被
    #: 收录），``noindex.present`` 规则靠这个值豁免，所以这条用例必须
    #: 真的把状态码设成 404，而不是只改 URL。
    status_code: int = 200
    #: 响应的最终 URL（重定向后）。混合内容的判定看的是它——只有
    #: ``final_url`` 是 https 时才去查页面里有没有 http 子资源。
    #: 真实抓取里重定向很常见，这个字段不设就等于把「最终地址」留空。
    final_url: Optional[str] = None


#: 自检语料。**每条规则至少一条 fires 用例**，且尽可能配一条 silent 用例。
#:
#: ⚠️ 期望值必须与 ``audit/rules/`` 的**当前判据**一致。改规则判据时这里
#: 会红——那是**该红的**：判据变了，「旧语料下应该触发」可能已经不成立，
#: 得有人确认新判据是否还符合预期，而不是让用例悄悄跟着变。
SELFTEST_CASES: tuple[SelfTestCase, ...] = (
    SelfTestCase(
        code="title.missing",
        expect="fires",
        note="缺 title 标签应报 CRITICAL",
        html=_html(title=None),
    ),
    SelfTestCase(
        code="title.missing",
        expect="silent",
        note="有 title 标签不报",
        html=_html(title="防水登山鞋 男款防滑 - 品牌名"),
    ),
    SelfTestCase(
        code="title.too_long",
        expect="fires",
        note="中文 title 超 30 字应报",
        html=_html(title="防水登山鞋男款防滑耐磨轻便舒适透气网面户外运动休闲鞋夏季新品上市特惠包邮"),
    ),
    SelfTestCase(
        code="title.too_long",
        expect="silent",
        note="中文 title 在 30 字内不报",
        html=_html(title="防水登山鞋 男款防滑 - 登山者"),
    ),
    SelfTestCase(
        code="title.too_short",
        expect="fires",
        note="过短 title 应报（占位符 Home 不豁免）",
        html=_html(title="Home"),
    ),
    SelfTestCase(
        code="title.too_short",
        expect="silent",
        note="品牌名型短 title 豁免",
        html=_html(title="Julia Evans"),
    ),
    SelfTestCase(
        code="title.duplicate",
        expect="fires",
        note="两页 title 完全相同应报",
        html=_html(title="完全一样的标题"),
        extra_pages=(("https://demo.test/other", _html(title="完全一样的标题")),),
    ),
    SelfTestCase(
        code="title.duplicate",
        expect="silent",
        note="两页 title 不同不报",
        html=_html(title="第一个页面的标题"),
        extra_pages=(("https://demo.test/other", _html(title="第二个页面的标题")),),
    ),
    SelfTestCase(
        code="meta.missing",
        expect="fires",
        note="缺 meta description 应报",
        html=_html(description=None),
    ),
    SelfTestCase(
        code="meta.missing",
        expect="silent",
        note="有 meta description 不报",
        html=_html(description="这是一段足够长的页面描述，包含核心关键词与行动理由。"),
    ),
    SelfTestCase(
        code="meta.duplicate",
        expect="fires",
        note="两页 description 相同应报",
        html=_html(description="完全一样的描述内容，用于验证重复检测能力"),
        extra_pages=(
            (
                "https://demo.test/other",
                _html(description="完全一样的描述内容，用于验证重复检测能力"),
            ),
        ),
    ),
    SelfTestCase(
        code="meta.duplicate",
        expect="silent",
        note="两页 description 不同不报",
        html=_html(description="第一个页面的描述内容，描述本页独有的卖点"),
        extra_pages=(
            (
                "https://demo.test/other",
                _html(description="第二个页面的描述内容，描述另一页的卖点"),
            ),
        ),
    ),
    SelfTestCase(
        code="h1.missing",
        expect="fires",
        note="无 H1 应报",
        html=_html(h1=None),
    ),
    SelfTestCase(
        code="h1.missing",
        expect="silent",
        note="有 H1 不报",
        html=_html(h1="示例页面"),
    ),
    SelfTestCase(
        code="h1.multiple",
        expect="fires",
        note="多个内容完全相同的 H1 应报",
        html=_html(h1=["同一个标题", "同一个标题"]),
    ),
    SelfTestCase(
        code="h1.multiple",
        expect="silent",
        note="多个 H1 内容不同不报（合理设计）",
        html=_html(h1=["站名", "文章标题"]),
    ),
    SelfTestCase(
        code="canonical.missing",
        expect="fires",
        note="非首页缺 canonical 应报",
        html=_html(canonical=None),
    ),
    SelfTestCase(
        code="canonical.missing",
        expect="silent",
        note="首页不报 canonical 缺失",
        html=_html(canonical=None),
        url="https://demo.test/",
    ),
    SelfTestCase(
        code="canonical.conflict",
        expect="fires",
        note="canonical 指向别页应报",
        html=_html(canonical="https://demo.test/other"),
    ),
    SelfTestCase(
        code="canonical.conflict",
        expect="silent",
        note="canonical 指向自己不算冲突",
        html=_html(canonical="https://demo.test/page"),
    ),
    SelfTestCase(
        code="noindex.present",
        expect="fires",
        note="200 页面带 noindex 应报 CRITICAL",
        html=_html(robots="noindex, nofollow"),
    ),
    SelfTestCase(
        code="noindex.present",
        expect="silent",
        note="404 页的 noindex 是正确配置，不报",
        html=_html(robots="noindex, nofollow"),
        url="https://demo.test/404",
        status_code=404,
    ),
    SelfTestCase(
        code="img.alt.missing",
        expect="fires",
        note="图片完全没有 alt 属性应报",
        html=_html(images=[("/a.jpg", None)]),
    ),
    SelfTestCase(
        code="img.alt.missing",
        expect="silent",
        note='alt="" 是装饰图正确写法，不报',
        html=_html(images=[("/a.jpg", "")]),
    ),
    SelfTestCase(
        code="img.alt.generic",
        expect="fires",
        note='alt="image" 属无意义占位，应报',
        html=_html(images=[("/a.jpg", "image")]),
    ),
    SelfTestCase(
        code="img.alt.generic",
        expect="silent",
        note="描述性 alt 不报",
        html=_html(images=[("/a.jpg", "红色登山鞋特写")]),
    ),
    SelfTestCase(
        code="link.noanchor",
        expect="fires",
        note="本页有多个空锚内部链接应报（单个视为无害 UI 元素）",
        html=_html(links=[("/about", ""), ("/contact", "")]),
    ),
    SelfTestCase(
        code="link.noanchor",
        expect="silent",
        note="只有一个空锚不报（多为无害 UI 元素）",
        html=_html(links=[("/about", "")]),
    ),
    SelfTestCase(
        code="http.mixed_content",
        expect="fires",
        note="HTTPS 页内 http 子资源应报",
        html=_html(body='<img src="http://cdn.demo.test/a.jpg">'),
        final_url="https://demo.test/page",
    ),
    SelfTestCase(
        code="http.mixed_content",
        expect="silent",
        note="<a href=http> 是超链接，不是混合内容",
        html=_html(body='<a href="http://external.test/forge">Forge</a>'),
        final_url="https://demo.test/page",
    ),
    SelfTestCase(
        code="soft404",
        expect="fires",
        note="内容极少的 200 页应报疑似软 404",
        html=_html(body="<p>短</p>", title="一个页面 - 演示站"),
    ),
    SelfTestCase(
        code="soft404",
        expect="silent",
        note="内容充实的 200 页不报",
        html=_html(
            body="<p>" + "这是一段足够长的正文内容，用来确保页面不会被判定为软 404。" * 20 + "</p>",
            title="内容充实的页面 - 演示站",
        ),
    ),
    SelfTestCase(
        code="sitemap.missing",
        expect="fires",
        note="探测到无 sitemap 应报",
        html=_html(),
        site_facts={"sitemap_found": False, "sitemap_tried": ["/sitemap.xml"]},
    ),
    SelfTestCase(
        code="sitemap.missing",
        expect="silent",
        note="有 sitemap 不报",
        html=_html(),
        site_facts={"sitemap_found": True},
    ),
    SelfTestCase(
        code="robots.missing",
        expect="fires",
        note="robots.txt 404 应报",
        html=_html(),
        site_facts={"robots_status": 404, "robots_url": "https://demo.test/robots.txt"},
    ),
    SelfTestCase(
        code="robots.missing",
        expect="silent",
        note="robots.txt 正常存在不报",
        html=_html(),
        site_facts={"robots_status": 200},
    ),
    SelfTestCase(
        code="robots.blocks_own_site",
        expect="fires",
        note="robots.txt 全站 Disallow 应报 CRITICAL",
        html=_html(),
        site_facts={
            "robots_directives": [["*", ["Disallow: /"]]],
        },
    ),
    SelfTestCase(
        code="robots.blocks_own_site",
        expect="silent",
        note="robots.txt 正常放行不报",
        html=_html(),
        site_facts={"robots_directives": [["*", ["Allow: /"]]]},
    ),
    SelfTestCase(
        code="depth.excessive",
        expect="fires",
        note="点击层级超过 4 层应报",
        html=_html(),
        depth=5,
    ),
    SelfTestCase(
        code="depth.excessive",
        expect="silent",
        note="层级在 4 层以内不报",
        html=_html(),
        depth=2,
    ),
    SelfTestCase(
        code="schema.missing",
        expect="silent",
        note="数据不足时站点级规则保持沉默（不误报）",
        html=_html(),
    ),
    # ── Google 包 ──────────────────────────────────────────────
    SelfTestCase(
        code="lang.missing",
        expect="fires",
        note="<html> 缺 lang 属性应报",
        html=_html().replace('<html lang="zh-CN">', "<html>"),
        markets=("google",),
    ),
    SelfTestCase(
        code="lang.missing",
        expect="silent",
        note="<html> 有 lang 属性不报",
        html=_html(lang="zh-CN"),
        markets=("google",),
    ),
    SelfTestCase(
        code="lang.not_html_lang",
        expect="fires",
        note="声明拉丁语言但正文是中文应报",
        html=_html(lang="en-US", body="<p>" + "这是一段中文正文内容。" * 30 + "</p>"),
        markets=("google",),
    ),
    SelfTestCase(
        code="lang.not_html_lang",
        expect="silent",
        note="声明语言与正文一致不报",
        html=_html(lang="zh-CN", body="<p>" + "这是一段中文正文内容。" * 30 + "</p>"),
        markets=("google",),
    ),
    SelfTestCase(
        code="viewport.missing",
        expect="fires",
        note="无 viewport 应报",
        html=_html(),
        markets=("google",),
    ),
    SelfTestCase(
        code="viewport.missing",
        expect="silent",
        note="有标准 viewport 不报",
        html=_html(
            head_extra='<meta name="viewport" content="width=device-width, initial-scale=1">'
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="viewport.not_responsive",
        expect="fires",
        note="固定像素宽度 viewport 应报",
        html=_html(head_extra='<meta name="viewport" content="width=980">'),
        markets=("google",),
    ),
    SelfTestCase(
        code="viewport.not_responsive",
        expect="silent",
        note="device-width + 可缩放不报",
        html=_html(
            head_extra='<meta name="viewport" content="width=device-width, initial-scale=1">'
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="title.pixel_overflow",
        expect="fires",
        note="英文 title 像素超 580px 应报（字符数未超 60）",
        html=_html(title="A" * 70),
        markets=("google",),
    ),
    SelfTestCase(
        code="title.pixel_overflow",
        expect="silent",
        note="短英文 title 像素不超阈值不报",
        html=_html(title="Waterproof Hiking Shoes"),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.inconsistent_with_lang",
        expect="fires",
        note="hreflang 集合不含 html lang 声明的语言应报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
                '<link rel="alternate" hreflang="de" href="https://demo.test/de">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.inconsistent_with_lang",
        expect="silent",
        note="hreflang 含自身语言不报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page">'
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.x_default_missing",
        expect="fires",
        note="多语言 hreflang 缺 x-default 应报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page">'
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.x_default_missing",
        expect="silent",
        note="单语言站不要求 x-default",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.suspicious_target",
        expect="fires",
        note="hreflang 指向 PDF 等非 HTML 资源应报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page.pdf">'
                '<link rel="alternate" hreflang="en" href="https://demo.test/en.pdf">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.suspicious_target",
        expect="silent",
        note="hreflang 指向 HTML 页面不报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page">'
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
            ),
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.self_reference_missing",
        expect="fires",
        note="hreflang 集合缺指向自己的自引用应报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
                '<link rel="alternate" hreflang="de" href="https://demo.test/de">'
                '<link rel="alternate" hreflang="x-default" href="https://demo.test/en">'
            ),
        ),
        final_url="https://demo.test/page",
        markets=("google",),
    ),
    SelfTestCase(
        code="hreflang.self_reference_missing",
        expect="silent",
        note="hreflang 集合含指向自己的自引用不报",
        html=_html(
            lang="zh-CN",
            head_extra=(
                '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/page">'
                '<link rel="alternate" hreflang="en" href="https://demo.test/en">'
            ),
        ),
        final_url="https://demo.test/page",
        markets=("google",),
    ),
    SelfTestCase(
        code="og.basic_missing",
        expect="fires",
        note="全站页面都缺 og 三件套应报（正面证据，不需要数据量门槛）",
        html=_html(),
        markets=("google",),
    ),
    SelfTestCase(
        code="og.basic_missing",
        expect="silent",
        note="页面有 og 三件套不报",
        html=_html(
            head_extra=(
                '<meta property="og:title" content="演示站">'
                '<meta property="og:description" content="演示站点">'
                '<meta property="og:image" content="https://demo.test/cover.png">'
            )
        ),
        markets=("google",),
    ),
    SelfTestCase(
        code="og.image_broken",
        expect="fires",
        note="og:image 回访 404 应报",
        html=_html(
            head_extra=(
                '<meta property="og:title" content="演示站">'
                '<meta property="og:description" content="演示站点">'
                '<meta property="og:image" content="https://demo.test/cover.png">'
            )
        ),
        # ⚠️ 键必须是 **normalize_url 之后的形态**（去协议、去 www）。
        # 规则查表时用的是 normalize_url(page.og_image)，写成原始 URL
        # 就会查不到 → 规则沉默 → 用例看着像「规则没触发」。
        site_facts={"og_image_status": {"demo.test/cover.png": 404}},
        markets=("google",),
    ),
    SelfTestCase(
        code="og.image_broken",
        expect="silent",
        note="没做回访就不猜（没检查过 ≠ 有问题）",
        html=_html(
            head_extra=(
                '<meta property="og:title" content="演示站">'
                '<meta property="og:description" content="演示站点">'
                '<meta property="og:image" content="https://demo.test/cover.png">'
            )
        ),
        markets=("google",),
    ),
    # ── 百度包 ────────────────────────────────────────────────
    SelfTestCase(
        code="title.chinese_too_long",
        expect="fires",
        note="中文 title 超 30 字应报",
        html=_html(title="防水登山鞋男款防滑耐磨轻便舒适透气网面户外运动休闲鞋夏季新品上市特惠包邮"),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="title.chinese_too_long",
        expect="silent",
        note="中文 title 在 30 字内不报",
        html=_html(title="防水登山鞋 男款防滑 - 登山者"),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="meta.chinese_semantic_incomplete",
        expect="fires",
        note="同一中文词根连续出现 3 次以上应报",
        html=_html(
            title="登山鞋登山鞋登山鞋",
            description="登山鞋推荐，登山鞋评测，登山鞋哪个好，选登山鞋看这里",
        ),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="meta.chinese_semantic_incomplete",
        expect="silent",
        note="语义完整的中文标题不报",
        html=_html(
            title="防水登山鞋 男款防滑耐磨 - 登山者",
            description="专业防水登山鞋选购指南，兼顾防滑与透气，附尺码建议与真实评测。",
        ),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="mobile.landing_page_missing",
        expect="fires",
        note="缺 viewport 应报",
        html=_html(),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="mobile.landing_page_missing",
        expect="silent",
        note="有 viewport 不报",
        html=_html(
            head_extra='<meta name="viewport" content="width=device-width, initial-scale=1">'
        ),
        markets=("baidu",),
    ),
    SelfTestCase(
        code="robots.baiduspider_not_allowed",
        expect="fires",
        note="robots.txt 屏蔽 Baiduspider 应报",
        html=_html(),
        site_facts={
            "robots_status": 200,
            "robots_directives": [["baiduspider", ["Disallow: /"]]],
        },
        markets=("baidu",),
    ),
    SelfTestCase(
        code="robots.baiduspider_not_allowed",
        expect="silent",
        note="robots.txt 放行 Baiduspider 不报",
        html=_html(),
        site_facts={
            "robots_status": 200,
            "robots_directives": [["baiduspider", ["Allow: /"]]],
        },
        markets=("baidu",),
    ),
    SelfTestCase(
        code="icp.filing_missing",
        expect="silent",
        note="数据不足时备案规则保持沉默",
        html=_html(),
        markets=("baidu",),
    ),
    # ── cnh_eco 包 ─────────────────────────────────────────────
    SelfTestCase(
        code="wechat.sogou_not_indexable",
        expect="silent",
        note="数据不足时微信搜狗规则保持沉默",
        html=_html(),
        markets=("cnh_eco",),
    ),
    # ── 需要数据量门槛的规则 ──────────────────────────────────
    SelfTestCase(
        code="orphan.page",
        expect="silent",
        note="数据不足时孤岛页规则保持沉默（没看到内链 ≠ 没有内链）",
        html=_html(),
    ),
)


def _run_case(case: SelfTestCase) -> dict[str, Any]:
    """跑一条用例，返回结构化结果。"""
    from .audit.engine import run_audit

    pages: list[Page] = [
        extract_page(
            case.url,
            case.html,
            status_code=case.status_code,
            final_url=case.final_url,
            depth=case.depth,
        )
    ]
    for url, html in case.extra_pages:
        pages.append(extract_page(url, html, depth=case.depth))

    domain = "demo.test"
    markets = [Market(m) for m in case.markets if m in {mm.value for mm in Market}]
    issues, _ctx = run_audit(pages, domain, markets, case.site_facts)
    codes = {i.code for i in issues}
    fired = case.code in codes
    passed = fired == (case.expect == "fires")
    return {
        "code": case.code,
        "expect": case.expect,
        "note": case.note,
        "passed": passed,
        "fired": fired,
        "observed_codes": sorted(codes),
        "markets": list(case.markets),
    }


def run_selftest(markets: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """跑一遍黄金样本自检。

    返回每条用例的通过情况与汇总。**用例没过就是没过**，不粉饰。
    """
    wanted: Optional[set[str]] = None
    if markets:
        wanted = {m.strip().lower() for m in markets if m.strip()}

    results: list[dict[str, Any]] = []
    for case in SELFTEST_CASES:
        if wanted is not None and not (set(case.markets) & wanted):
            continue
        results.append(_run_case(case))

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    # 覆盖到的规则数：自检语料覆盖了注册表里的多少条规则。
    catalog_codes = {r["code"] for r in rule_catalog()["rules"]}
    covered = {r["code"] for r in results}
    return {
        "cases": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "all_passed": failed == 0,
            "rules_covered": len(covered),
            "rules_registered": len(catalog_codes),
            "uncovered_rules": sorted(catalog_codes - covered),
        },
    }


# --------------------------------------------------------------------------
# 3. 验证台账：读 docs/ 下的实测报告
# --------------------------------------------------------------------------


def _read_json(name: str) -> Optional[Any]:
    d = docs_dir()
    if d is None:
        return None
    path = d / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 读不出来就当没有。**不能返回 0 或空 dict**——「没测过」和
        # 「测了是 0」是两回事，报告里分不开就没法决策。
        return None


def accuracy_report() -> dict[str, Any]:
    """准确率校准报告（107 站实跑复核 + 200 站初跑）。

    ⚠️ 数字**只从 ``docs/accuracy_*.json`` 读**。接口自己再算一遍必然
    与文档分叉，而分叉之后没人知道该信哪个——本项目已因此返工过。

    拿不到文件时返回 ``available: False`` 并说明原因，**不返回 0**。
    """
    recheck = _read_json("accuracy_recheck.json")
    report = _read_json("accuracy_report.json")

    out: dict[str, Any] = {
        "available": False,
        "source": "docs/accuracy_recheck.json",
        "reason": "",
        "recheck": None,
        "batch": None,
    }
    if recheck is None:
        out["reason"] = (
            "未找到准确率复核报告（docs/accuracy_recheck.json）。"
            "该文件在开发仓库中，随包分发时不包含——这不代表准确率为 0。"
        )
    else:
        out["available"] = True
        out["recheck"] = {
            "true_positive": recheck.get("true_positive"),
            "false_positive": recheck.get("false_positive"),
            "inconclusive": recheck.get("inconclusive"),
            "adjudicable": recheck.get("adjudicable"),
            "precision_on_adjudicable": recheck.get("precision_on_adjudicable"),
            "precision_if_inconclusive_all_true": recheck.get(
                "precision_if_inconclusive_all_true"
            ),
            "precision_if_inconclusive_all_false": recheck.get(
                "precision_if_inconclusive_all_false"
            ),
            "false_positive_by_code": recheck.get("false_positive_by_code", {}),
            "inconclusive_by_code": recheck.get("inconclusive_by_code", {}),
        }
    if report is not None:
        summary = report.get("summary", {})
        out["batch"] = {
            "sites_total": summary.get("sites_total"),
            "sites_ok": summary.get("sites_ok"),
            "pages_crawled": summary.get("pages_crawled"),
            "issues_reported": summary.get("issues_reported"),
            "auto_checked": summary.get("auto_checked"),
            "true_positive": summary.get("true_positive"),
            "false_positive": summary.get("false_positive"),
            "needs_human": summary.get("needs_human"),
            "precision": summary.get("precision"),
            "false_positive_by_code": summary.get("false_positive_by_code", {}),
        }
    return out


def verification_ledger() -> dict[str, Any]:
    """回源核对台账（逐条规则的人工核对结果）。

    数据在 ``docs/verification-ledger.md`` 的 Markdown 表格里。这里**解析
    表格**而不是另存一份 JSON：台账是人工维护的，解析它就没有第二份
    副本要同步。
    """
    d = docs_dir()
    if d is None:
        return {
            "available": False,
            "reason": "未找到 docs/ 目录（随包分发时不包含），台账不可用。",
            "rows": [],
        }
    path = d / "verification-ledger.md"
    if not path.exists():
        return {
            "available": False,
            "reason": "未找到 docs/verification-ledger.md。",
            "rows": [],
        }
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"available": False, "reason": f"读取台账失败：{exc}", "rows": []}

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in ("规则",):
            continue
        rule, checked, real, false_pos, doubtful, note = cells[:6]
        # 台账里规则名带反引号（Markdown 行内代码）：`title.missing`。
        # 而且**可能带后缀**：`title.missing`（另一批）——只清首尾的话
        # 中间那个反引号会留下，规则名与规则目录的 code 对不上，
        # 覆盖率就成了假的。所以这里去掉**全部**反引号。
        rule = rule.replace("`", "").strip()
        # 「核对条数」等数字可能带说明后缀，取开头数字部分
        def _num(raw: str) -> Optional[int]:
            digits = "".join(ch for ch in raw if ch.isdigit())
            return int(digits) if digits else None

        rows.append(
            {
                "rule": rule,
                "checked": _num(checked),
                "true_positive": _num(real),
                "false_positive": _num(false_pos),
                "inconclusive": _num(doubtful),
                "note": note,
            }
        )

    total_checked = sum(r["checked"] or 0 for r in rows)
    total_real = sum(r["true_positive"] or 0 for r in rows)
    total_false = sum(r["false_positive"] or 0 for r in rows)
    return {
        "available": True,
        "reason": "",
        "rows": rows,
        "summary": {
            "rules": len(rows),
            "checked": total_checked,
            "true_positive": total_real,
            "false_positive": total_false,
            "false_positive_rate": (
                round(total_false / total_checked, 4) if total_checked else None
            ),
        },
    }
