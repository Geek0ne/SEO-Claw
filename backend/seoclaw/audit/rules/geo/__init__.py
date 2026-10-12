"""GEO / AI 搜索可引用性规则包。

## ⚠️ 这个包默认不加载

``default_registry()`` 只加载 base / google / baidu / cnh_eco。GEO 必须显式开启::

    registry.load_module_rules(_import_rules("geo"))

**为什么不进 base**：base 的 39 条刚在 107 个真实站点上验到 97.0% 严格准确率。
GEO 这类"AI 搜索友好度"结论的证据强度远不如它，混进去会污染那条基线，
让好规则一起被拖下水。

## ⚠️ 这个领域最大的坑：大部分"GEO 优化"建议是无法验证的

搜索圈流传的 GEO 建议里，相当一部分**没有可验证依据**。本包刻意只实现
**结构上真的能查、且不依赖未公开算法**的几条，其余全部记录在下方
「不实现」一节。理由很直接：

- **用户按一条错误建议改了站，改完没有任何数据能证明有没有变好** ——
  这比没有建议更糟，因为它消耗信任。

## 实现了什么（依据都能核对）

| code | 依据 |
|---|---|
| `geo.no_question_headings` | 生成式引擎按「问题 → 段落」抽取答案。一页 500+ 字却没有任何问句式小标题，说明答案没有被结构化包裹。这是**页内完整标题列表**上的阳性结论，不依赖抓取覆盖率 |
| `geo.no_outbound_references` | 可引用性高���页面通常给出处。无任何出链的 500+ 字内容页，在"这一条的依据是什么"这个问题上答不上来。页内链接列表是完整的，属阳性结论 |
| `geo.flat_structure` | 800+ 字的正文只有 0~1 个小标题 —— 内容被压成一大段，抽取器无从切分。同样是页内完整数据的阳性结论 |
| `geo.faq_structure_mismatch` | 页面自称 FAQ / 常见问题，却没有任何问句式条目。自相矛盾，属**逻辑一致性**判断，不是算法猜测 |

## 不实现（以及为什么）

- **"AI 会不会引用这页"** —— 需要知道各家的检索与引用策略，没有公开依据。
  声称能算这个分，等于编造。
- **"内容新鲜度"** —— `Page.last_modified` 只反映 HTTP 头，静态 HTML 里
  没有权威发布日期。拿它排序会产生大面积误报，而新鲜度是否影响引用无从验证。
- **"需要 E-E-A-T 信号"**（作者、资质、引用） —— `Page` 模型没有作者字段，
  提取层也没采集。看不到就是看不到，不靠猜。
- **"关键词/实体覆盖"** —— 生成式检索按语义召回，不按关键词密度。
  照搬传统 SEO 的密度阈值是反向优化。
- **"FAQPage 结构化数据"** —— base 包 `schema.missing` 已覆盖有无结构化数据，
  再加一条只是换个名字重复报，且会让人误以为加了 schema 就能被引用。
"""

from __future__ import annotations

import re
from typing import Iterable

from ....models import Issue, Page, Scope, Severity
from ...engine import Rule, RuleContext

# 疑问句式。覆盖中英两种写法：中文用问号/疑问词，英文用 ? 与疑问词开头。
_CN_Q_WORDS = ("什么", "怎么", "如何", "为什么", "哪些", "哪个", "是否", "多久", "多少")
_EN_Q_WORDS = (
    "what", "how", "why", "when", "where", "which", "who", "whom", "whose",
    "can", "should", "is", "are", "do", "does", "did",
)
# ⚠️ 中文疑问词**不能带 \b**。
#
# 踩过的坑：`^怎么\b` 在中文里永远匹配不上 —— \b 是「词边界」，
# 而「么」和「收」都是词字符（\w），两个词字符之间不存在边界。
# 结果 `怎么收费` / `为什么选择我们` 全被判成非问句，
# **geo.no_question_headings 在每个中文站上都会误报**，
# 而中文站正是 GEO 规则的主力场景。
#
# 中文不需要词边界：这些疑问词本身不会被普通词包含（不会出现在「怎么着」
# 这种词内部而改变含义），直接前缀匹配即可。英文分支必须保留 \b，
# 否则 "is" 会命中 "issue" 的开头。
_QA_RE = re.compile(
    r"[?？]"
    r"|^(" + "|".join(_CN_Q_WORDS) + r")"
    r"|^(what|how|why|when|where|which|who|whom|whose|can|could|should|would|do|does|did|is|are|will)\b",
    re.I,
)

# 自称 FAQ 的措辞。命中它却一个问句都没有 → 自相矛盾。
_FAQ_CLAIM_RE = re.compile(r"faq|常见问题|问与答|问答|q\s*&\s*a", re.I)

# 低于这个字数不做"结构"类判断：一页 50 字的落地页不需要 FAQ 结构。
_MIN_WORDS = 500
_MIN_WORDS_DEEP = 800
# 小标题少于这个数算「压成一大段」
_MIN_HEADINGS = 3


def _is_js_shell(page: Page) -> bool:
    """这一页的静态 HTML 是不是「壳」。

    ⚠️ GEO 这 4 条规则**全部**是靠「没看到 X」下结论的（没有问句式小标题、
    没有出链、小标题太少）。静态壳里「没看到 X」只说明 X 是 JS 注入的，
    推不出「页面没有 X」——和 base 包的 title.missing / h1.missing
    在 agoda 上踩的坑完全一样。

    所以四条规则共用这一道守卫。缺了它，GEO 包会在这类站点上大面积误报。
    """
    return bool(page.likely_js_rendered)


def _is_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_QA_RE.search(t))


def _subheadings(page: Page, min_level: int = 2) -> list[str]:
    """h2 及以下的小标题（h1 是页面主标题，不算结构）。"""
    return [t for lvl, t in (page.headings or []) if lvl >= min_level and t and t.strip()]


class NoQuestionHeadings(Rule):
    """长内容页没有任何问句式小标题 → 答案没有被结构化包裹。"""

    code = "geo.no_question_headings"
    severity = Severity.LOW
    scope = Scope.PAGE
    title = "长内容页没有任何问句式小标题"
    description = (
        "这一页有 500 字以上正文，但没有任何问句式的小标题。"
        "生成式引擎回答问题时，倾向于从「问题 + 紧随的答案段落」里抽取。"
        "内容压在一大段里，抽取器拿不到明确的答案边界。"
    )
    fix_hint = (
        "按读者真正会问的问题重组小标题：一个 h2 问一个问题，"
        "紧跟的段落就回答它。不要为了凑数硬拆，标题必须是你页面里真的有答案的内容。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.is_html or page.error or page.word_count < _MIN_WORDS:
            return
        if _is_js_shell(page):
            return
        subs = _subheadings(page)
        if not subs:
            return  # 连小标题都没有 → 那是 geo.flat_structure 的职责，不重复报
        if any(_is_question(t) for t in subs):
            return
        yield self._issue(
            page,
            {
                "verdict": "likely_not_structured_for_qa",
                "verdict_explain": (
                    f"本页有 {len(subs)} 个小标题，但没有一个是问句式。"
                    "这是结构观察，不是对 AI 引用率的预测 —— 引用行为没有公开依据可算。"
                ),
                "word_count": page.word_count,
                "subheadings": subs[:12],
                "subheading_count": len(subs),
                "caveat": "改完不代表会被引用。这只让内容更容易被切分成答案片段。",
            },
        )


class NoOutboundReferences(Rule):
    """长内容页没有任何出链 → 无法回答「这条依据是什么」。"""

    code = "geo.no_outbound_references"
    severity = Severity.INFO
    scope = Scope.PAGE
    title = "长内容页没有任何外部参考链接"
    description = (
        "这一页有 500 字以上正文，但一条外部链接都没有。"
        "读者（和抽取器）无法判断内容的依据来自哪里。"
    )
    fix_hint = (
        "在给出数据、统计、定义的地方给出处，链到权威来源。"
        "只链你真的引用过的来源 —— 凑数的外链比没有外链更糟。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.is_html or page.error or page.word_count < _MIN_WORDS:
            return
        if _is_js_shell(page):
            return
        n = page.external_link_count or 0
        if n > 0:
            return
        yield self._issue(
            page,
            {
                "verdict": "no_citations_found",
                "verdict_explain": (
                    "页内链接清单是完整的（不是没抓到），确实一条出链都没有。"
                ),
                "word_count": page.word_count,
                "internal_link_count": page.internal_link_count,
                "external_link_count": 0,
                "caveat": "这条是内容可信度问题，不是排名问题。SEO 上不加分不减分。",
            },
        )


class FlatStructure(Rule):
    """长正文但小标题极少 → 内容被压成一大段。"""

    code = "geo.flat_structure"
    severity = Severity.LOW
    scope = Scope.PAGE
    title = "长正文被压成一大段，缺少小标题"
    description = (
        "这一页正文超过 800 字，小标题却只有 0~1 个。"
        "内容没有分段结构，抽取器无从切分成可引用的片段。"
    )
    fix_hint = (
        "按主题切成 h2/h3。切分点用读者会问的问题或内容里真实的转折，"
        "而不是按字数平均切。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.is_html or page.error or page.word_count < _MIN_WORDS_DEEP:
            return
        if _is_js_shell(page):
            return
        subs = _subheadings(page)
        if len(subs) >= _MIN_HEADINGS:
            return
        yield self._issue(
            page,
            {
                "verdict": "content_not_segmented",
                "verdict_explain": (
                    f"正文 {page.word_count} 字，小标题 {len(subs)} 个。"
                    "这是结构观察，不代表一定会被引用或不被引用。"
                ),
                "word_count": page.word_count,
                "subheadings": subs[:12],
                "subheading_count": len(subs),
                "heading_levels": sorted({lvl for lvl, _ in (page.headings or [])}),
                "caveat": "短文不需要切分。这条只针对真的写成一大段的页面。",
            },
        )


class FaqStructureMismatch(Rule):
    """自称 FAQ 却一个问句都没有 —— 逻辑自相矛盾，不是算法猜测。"""

    code = "geo.faq_structure_mismatch"
    severity = Severity.MEDIUM
    scope = Scope.PAGE
    title = "页面自称 FAQ / 常见问题，却没有任何问句式条目"
    description = (
        "页面标题或小标题里出现了 FAQ / 常见问题 / Q&A，但正文里没有任何问句式条目。"
        "这是页面自己的承诺与内容不符。"
    )
    fix_hint = (
        "要么把内容改成真正的问答结构（问题 + 答案成对出现），"
        "要么去掉 FAQ 这个说法 —— 标题承诺了结构、内容却给不出，"
        "读者会认为这是凑数。"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.is_html or page.error or page.word_count < 200:
            return
        if _is_js_shell(page):
            return
        head_texts = [t for _, t in (page.headings or []) if t] + [page.title or ""]
        claims = [t for t in head_texts if _FAQ_CLAIM_RE.search(t)]
        if not claims:
            return
        subs = _subheadings(page)
        if any(_is_question(t) for t in subs):
            return
        # 正文里出现问号也算「有问答结构」，只查小标题会误报
        body_q = len(re.findall(r"[?？]", page.text or ""))
        if body_q >= 2:
            return
        yield self._issue(
            page,
            {
                "verdict": "faq_claimed_but_no_questions",
                "verdict_explain": (
                    f"页面自称 {claims[0]!r}，但小标题 {len(subs)} 个里没有问句，"
                    f"正文问号仅 {body_q} 处。这是自相矛盾，不涉及任何算法猜测。"
                ),
                "claims_in": claims[:4],
                "subheadings": subs[:12],
                "body_question_marks": body_q,
                "caveat": "若这些 FAQ 在 JS 里注入，本工具看不到 —— "
                "请先确认页面源码里确实没有。",
            },
        )


# ⚠️ 各规则不写 market 属性，沿用引擎默认的 Market.BASE，只为复用既有加载/
# 过滤路径。本包默认不被 default_registry() 加载，必须显式开启（见模块
# docstring），所以 BASE 不会让 GEO 悄悄混进常规扫描。
__all__ = [
    "NoQuestionHeadings",
    "NoOutboundReferences",
    "FlatStructure",
    "FaqStructureMismatch",
]