"""内容 Brief 生成：从 SERP 快照 + 本站页面，产出一份可执行的写作 Brief。

## 这一层的诚实边界（最重要的一条）

``serp_snapshots`` 存的是竞品的 **url / title / snippet / features**，
**没有竞品正文**。所以本模块**不会**输出「Top10 平均正文 1800 字」这种结论——
那需要真去爬一遍竞品，拿不到就说拿不到。

能做的是**标题层共性**，因为标题就在手里：
- 10 条标题里几个用了「价格/多少钱」
- 几个带了品牌名
- 几个用了疑问句式

这些结论**可核对**（用户可以自己去搜索页比对），比一个编出来的字数区间有用。

## 字数建议从哪儿来

从**本站已有页面**的 word_count 分布来，不是从竞品。
理由：本工具能验证的只有自家页面的实际表现；拿竞品字数当目标，
是在让用户追一个我无法验证的数字。

## 不做的事

- 不编搜索量（``volume`` 缺失就是缺失，见 :mod:`seoclaw.keywords.expand`）
- 不猜「还差几篇」（缺 content gap 的定量依据就说缺）
- 差异化机会只从**能看到的证据**推：Top10 缺什么维度、snippet 都在讲什么
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .db.models import Intent, Market
from .keywords.expand import tokenize

# 标题里的意图信号词 → 中文标签。用于统计 Top10 标题的修饰模式。
_PRICE_TOKENS = {"价格", "多少钱", "费用", "报价", "收费", "价目", "价格表"}
_HOWTO_TOKENS = {"怎么", "如何", "教程", "步骤", "指南", "方法", "入门", "做法"}
_COMPARE_TOKENS = {"对比", "哪个", "比较", "区别", "vs", "versus", "区别是", "推荐"}
_BRAND_HINT = re.compile(r"\b[a-z0-9]{2,}\.(?:com|cn|net|org|io|co)\b", re.I)

# 页型：不同搜索意图对应不同页面形态。
# 这是本工具**唯一**的硬知识，来源是 SERP 通用规律，不是猜的。
_PAGE_TYPE_BY_INTENT: dict[Intent, str] = {
    Intent.INFORMATIONAL: "内容页（教程 / 说明 / 指南）",
    Intent.NAVIGATIONAL: "首页或分类入口页（少用大段正文）",
    Intent.COMMERCIAL: "对比评测页（列参数、给结论）",
    Intent.TRANSACTIONAL: "产品/购买页（价格、库存、行动按钮）",
}


@dataclass
class SerpEntry:
    """一条 SERP 记录。字段名与 ``serp_snapshots`` 表对齐。"""

    position: int
    url: str
    title: str = ""
    snippet: Optional[str] = None
    features: list[Any] = field(default_factory=list)


@dataclass
class PageSignal:
    """本站页面，用于算字数基线。"""

    url: str
    title: str = ""
    h1: list[str] = field(default_factory=list)
    word_count: int = 0


@dataclass
class ContentBrief:
    """一份内容 Brief。字段对应 ``content_briefs`` 表。"""

    target_url: str
    keyword: str
    market: str
    intent: Optional[str] = None
    page_type: str = ""
    title_candidates: list[str] = field(default_factory=list)
    #: Top10 标题层共性。每条都要能被用户自己核对。
    serp_common: dict[str, Any] = field(default_factory=dict)
    #: 本站字数基线。明确标注来源是「自家页面」，不是竞品。
    own_length_baseline: dict[str, Any] = field(default_factory=dict)
    #: 差异化机会：每条附证据。
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    #: 明确标注「拿不到」的东西，防止下游误以为已覆盖。
    not_available: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "target_url": self.target_url,
            "keyword": self.keyword,
            "market": self.market,
            "intent": self.intent,
            "page_type": self.page_type,
            "title_candidates": self.title_candidates,
            "serp_common": self.serp_common,
            "own_length_baseline": self.own_length_baseline,
            "opportunities": self.opportunities,
            "not_available": self.not_available,
        }


def _classify_title(title: str) -> set[str]:
    """给一个标题打上意图修饰标签。"""
    toks = set(tokenize(title))
    raw = title.lower()
    tags: set[str] = set()
    if toks & _PRICE_TOKENS or "价格" in raw or "多少钱" in raw:
        tags.add("价格型")
    if toks & _HOWTO_TOKENS or "?" in raw or "？" in title:
        tags.add("教程型")
    if toks & _COMPARE_TOKENS or "对比" in raw:
        tags.add("对比型")
    return tags


def analyze_serp_titles(entries: Sequence[SerpEntry]) -> dict[str, Any]:
    """统计 Top10 标题的修饰模式。

    只做**标题层**统计——这是唯一我们真的持有原文的竞品信息。
    """
    titles = [e.title for e in entries if e.title]
    if not titles:
        return {"available": False, "reason": "SERP 快照里没有任何标题"}

    tag_count: Counter[str] = Counter()
    brand_count = 0
    lens: list[int] = []
    for t in titles:
        tag_count.update(_classify_title(t))
        if _BRAND_HINT.search(t):
            brand_count += 1
        lens.append(len(t))

    n = len(titles)
    lens_sorted = sorted(lens)
    median_len = lens_sorted[len(lens_sorted) // 2]
    return {
        "available": True,
        "titles_analyzed": n,
        "modifiers": {
            tag: {"count": c, "ratio": round(c / n, 3)} for tag, c in tag_count.most_common()
        },
        "brand_in_title": {"count": brand_count, "ratio": round(brand_count / n, 3)},
        "title_length": {
            "median": median_len,
            "min": lens_sorted[0],
            "max": lens_sorted[-1],
        },
        "note": "仅统计标题层。本工具未抓取竞品正文，得出正文长度结论。",
    }


def own_length_baseline(pages: Sequence[PageSignal]) -> dict[str, Any]:
    """用**本站**页面算字数基线。

    ⚠️ 来源必须写清楚是自家页面。让用户拿自家数据做对照，
    而不是去追一个我验证不了的竞品数字。
    """
    counts = sorted(p.word_count for p in pages if p.word_count > 0)
    if not counts:
        return {
            "available": False,
            "source": "own_pages",
            "reason": "本站已抓页面里没有带正文长度的记录",
        }
    return {
        "available": True,
        "source": "own_pages",
        "note": "来源是本站已抓页面，不是竞品——竞品正文本工具没有抓。",
        "n": len(counts),
        "median": counts[len(counts) // 2],
        "min": counts[0],
        "max": counts[-1],
    }


def _site_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower().replace("www.", "") if m else ""


def find_opportunities(
    keyword: str,
    entries: Sequence[SerpEntry],
    own_pages: Sequence[PageSignal],
) -> list[dict[str, Any]]:
    """找差异化机会。**每条都必须附证据**，且只从能看到的东西推。"""
    out: list[dict[str, Any]] = []
    kw_toks = set(tokenize(keyword))
    if not kw_toks:
        return out

    # 机会 1：某个修饰维度 Top10 用得少
    common = analyze_serp_titles(entries)
    if common.get("available"):
        mods = common.get("modifiers") or {}
        used = {t for t, v in mods.items() if v["ratio"] >= 0.5}
        all_modes = {"价格型", "教程型", "对比型"}
        for m in sorted(all_modes - used):
            out.append(
                {
                    "kind": "underused_modifier",
                    "title": f"Top10 里 {common['titles_analyzed']} 条只有"
                    f"{mods.get(m, {}).get('count', 0)} 条用了「{m}」",
                    "evidence": {
                        "titles_analyzed": common["titles_analyzed"],
                        "modifier_counts": mods,
                    },
                    "caveat": "标题层统计。Top10 不用不代表做了一定更好，"
                    "只说明这是个少人做的角度。",
                }
            )

    # 机会 2：竞品标题里反复出现的词，我们一个都没在用
    competitor_terms: Counter[str] = Counter()
    for e in entries:
        competitor_terms.update(set(tokenize(e.title)) - kw_toks)
    own_terms: set[str] = set()
    for p in own_pages:
        own_terms.update(tokenize(p.title + " " + " ".join(p.h1)))
    missing = [
        (t, c)
        for t, c in competitor_terms.most_common(12)
        if c >= 2 and t not in own_terms and len(t) >= 2
    ]
    if missing:
        out.append(
            {
                "kind": "missing_terms",
                "title": "竞品标题里高频出现、我们站内一个都没用的词",
                "evidence": {
                    "missing": [{"term": t, "count": c} for t, c in missing],
                    "competitor_titles_analyzed": len(entries),
                },
                "caveat": "「没在用」不等于「该用」。先确认这些词真的相关，"
                "堆砌无关热词是反向优化。",
            }
        )

    # 机会 3：SERP 特性（featured snippet / 图片包…）告诉我们用户在找什么形态
    features: Counter[str] = Counter()
    for e in entries:
        for f in e.features or []:
            features[str(f)] += 1
    if features:
        out.append(
            {
                "kind": "serp_features",
                "title": "SERP 特性提示了用户期待的页面形态",
                "evidence": {"features": dict(features)},
                "caveat": "SERP 特性是环境特征，不保证与内容质量相关。",
            }
        )
    return out


def build_title_candidates(
    keyword: str,
    intent: Optional[str],
    site: str,
    limit: int = 5,
) -> list[str]:
    """生成标题候选。

    ⚠️ 刻意给得很「土」——就是套模板的组合。
    标题是全站最该自己想清楚的字段，工具给 5 个模板反而是在替用户做决定。
    这里只负责把「必须包含什么」摆出来。
    """
    site_s = site.split(".")[0] if site else ""
    base = [
        f"{keyword} 完整指南",
        f"{keyword}：从入门到上手",
        f"{site_s} 的{keyword}怎么做",
    ]
    if intent == Intent.COMMERCIAL:
        base.insert(0, f"{keyword} 怎么选 · 对比与建议")
    elif intent == Intent.TRANSACTIONAL:
        base.insert(0, f"{keyword} · 价格与服务说明")
    elif intent == Intent.NAVIGATIONAL:
        base.insert(0, f"{site_s} · {keyword}")
    return base[:limit]


def generate_brief(
    keyword: str,
    *,
    target_url: str,
    market: Market = Market.GOOGLE,
    intent: Optional[Intent] = None,
    serp_entries: Sequence[SerpEntry] = (),
    own_pages: Sequence[PageSignal] = (),
) -> ContentBrief:
    """生成一份内容 Brief。

    所有字段在数据不足时**保持 None / 空 + not_available 说明**，
    不用默认值填充。
    """
    entries = list(serp_entries)
    common = analyze_serp_titles(entries)
    baseline = own_length_baseline(own_pages)

    not_available: list[str] = [
        "竞品正文长度（本工具未抓竞品正文，只存了标题/摘要）",
        "竞品正文结构（标题层级、字数、素材数量）",
        "该词的实际搜索量（无付费数据源）",
        "我方当前排名（需接 Search Console）",
    ]

    site = _site_of(target_url)
    brief = ContentBrief(
        target_url=target_url,
        keyword=keyword,
        market=market.value,
        intent=intent.value if intent else None,
        page_type=(
            _PAGE_TYPE_BY_INTENT.get(intent, "未分类（缺 intent，建议先人工判定）")
        ),
        title_candidates=build_title_candidates(keyword, intent, site),
        serp_common=common,
        own_length_baseline=baseline,
        opportunities=find_opportunities(keyword, entries, own_pages),
        not_available=not_available,
    )

    # 一个已有页面在竞争这个词 → 那是「优化」不是「新建」
    competing = [p.url for p in own_pages if kw_in_page(keyword, p)]
    if competing:
        brief.opportunities.insert(
            0,
            {
                "kind": "already_ranked",
                "title": f"本站已有 {len(competing)} 个页面在竞争这个词",
                "evidence": {"urls": competing[:10]},
                "caveat": "已有页面时应优先优化它们，而不是新开一篇——"
                "同站多页竞争同一词会互相稀释权重。",
            },
        )
    return brief


def kw_in_page(keyword: str, page: PageSignal) -> bool:
    """粗判某页面是否在竞争这个词。

    刻意保守：只看标题/H1 是否含关键词的任一 token。
    「正文提过一次」太松，会把一堆页面都算成在竞争。
    """
    toks = set(tokenize(keyword))
    if not toks:
        return False
    return bool(toks & set(tokenize(page.title + " " + " ".join(page.h1))))