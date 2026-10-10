"""关键词扩展：从站点自有语料里挖出候选词，并给出可核对的证据。

## 为什么先做「语料挖掘」而不是「LLM 扩写」

PLAN 原本写的是 jieba + pgvector 语义聚类，但语义聚类要 embedding，
**embedding 同样要 API key**。所以这一层刻意做成**纯离线、确定性**的：
同样的语料，跑一百次结果完全一样。

这不是降级的临时方案。词扩展真正值钱的部分是**证据**：
「这个词和你已有的 8 个页面共现 12 次，其中 5 次出现在 title 里」——
用户能自己点开核对。而 embedding 给出的「语义相似度 0.87」谁也核对不了。

## 三种扩展来源，各有不同的可信度

1. **共现挖掘**（最强）：从站内已抓页面里找和现有词共同出现的词。
   证据是可核对的页面列表。
2. **形态变体**（中等）：中文疑问/修饰前缀、英文复数与动词形态。
   「怎么 / 多少钱 / 哪个好」通常搜索意图相同。
3. **标题 n-gram 复合**（最弱）：从 title/h1 里拼出高频连续词组。
   容易造出不通顺的词，所以要求**至少跨 2 个页面**共现。

## 不做的事

- **不猜搜索量**。没有付费数据源就是没有，`volume=None` 明确留空。
  用 0 冒充「搜索量真的是 0」比不给更糟——用户会据此放弃一个词。
- **不跨站借用词**。所有候选必须来自本站在地语料，否则相关性无从谈起。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# 中文停用词：只收高频虚词，不收可能构成搜索意图的实词。
# 「的/了/是」该去，「推荐/教程/价格」不该去——那些正是用户会搜的词。
_CN_STOPWORDS = frozenset(
    """
的 了 是 在 和 有 就 都 而 及 与 也 很 你 我 他 她 它 们 这 那 之 于 或 一个
我们 你们 他们 这个 那个 这些 那些 什么 怎么 如何 可以 需要 进行 通过 使用
以及 并且 因为 所以 但是 如果 已经 还有 一些 一样 这些 时候 之后 现在 目前
能够 应该 可能 主要 相关 关于 对于 由于 通过 进行 表示 认为
""".split()
)

_EN_STOPWORDS = frozenset(
    """
a an the and or of to in for on with at by from as is are was were be been
this that these those it its your our their my we you they he she i
what how why when where which who whom can could should would will shall
do does did done have has had not no yes if then than so such about into
""".split()
)

# 停用词没覆盖到的残留：纯数字、单个字母、纯符号。
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'\-]*|[\u4e00-\u9fff]+")

# 中文疑问/修饰前缀 —— 加在前缀上通常不改变搜索意图。
_CN_PREFIXES = ("怎么", "如何", "多少钱", "哪个", "哪种", "为什么", "是不是", "推荐", "教程", "价格")

# 英文形态变体：原形 → 复数/动词形态。只做安全的规则变换，
# 不用词库（那要额外依赖且对中文站无用）。
_EN_VARIANTS = (
    ("s", ""),          # plugins -> plugin
    ("ing", ""),        # running -> run
    ("ed", ""),         # pricing -> pric（不完美，但聚类时方向对）
    ("es", ""),
)


@dataclass
class ExpansionCandidate:
    """一个候选扩展词。

    ⚠️ ``volume`` 默认 None 而不是 0：没有付费数据源就是不知道。
    0 表示「这个词搜索量真的是 0」，会把用户引向错误的放弃决定。
    """

    term: str
    score: float
    source: str  # cooccurrence | morphology | ngram
    #: 支撑这个候选的站内 URL 列表（已去重、已截断）。用户可点开核对。
    evidence_urls: list[str] = field(default_factory=list)
    #: 该词与哪些已有词共现（cooccurrence 才有）。
    co_occurs_with: list[str] = field(default_factory=list)
    #: 出现在几个页面上。
    pages_seen: int = 0
    volume: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "term": self.term,
            "score": round(self.score, 4),
            "source": self.source,
            "evidence_urls": self.evidence_urls,
            "co_occurs_with": self.co_occurs_with,
            "pages_seen": self.pages_seen,
            "volume": self.volume,
        }


def tokenize(text: str) -> list[str]:
    """切成归一化 token。

    中文用 jieba 的搜索模式（它会把「SEO优化怎么做」切成
    「seo / 优化 / 优化怎么 / 怎么做」，长词优先，对搜索词更有意义）。
    英文按单词切。

    拉丁词统一小写——「SEO」和「seo」是同一个搜索意图，
    不归一会让同一个词在库里出现两次。
    """
    if not text:
        return []
    try:
        import jieba

        raw = jieba.cut_for_search(text)
    except Exception:  # noqa: BLE001 — jieba 缺失时退回字符切分，不让整层崩掉
        raw = _TOKEN_RE.findall(text)

    out: list[str] = []
    for tok in raw:
        tok = tok.strip().lower()
        if not tok or tok in _CN_STOPWORDS or tok in _EN_STOPWORDS:
            continue
        if tok.isdigit() or (len(tok) == 1 and tok.isalpha()):
            continue
        out.append(tok)
    return out


def _is_cjk(tok: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in tok)


def _page_tokens(pages: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
    """(url, text) → {url: 该页面的 token 集合}。

    同一页出现两次只算一次：关键词共现关心的是「覆盖了多少个页面」，
    一个页面里堆 20 次不会让这个词更值得做。
    """
    per_page: dict[str, set[str]] = {}
    for url, text in pages:
        per_page.setdefault(url, set()).update(tokenize(text))
    return per_page


def expand(
    seeds: list[str],
    pages: Iterable[tuple[str, str]],
    *,
    max_candidates: int = 50,
    min_pages: int = 2,
) -> list[ExpansionCandidate]:
    """从站内语料里挖候选词。

    :param seeds: 已知关键词（通常是已跟踪的词）。
    :param pages: ``(url, text)`` 序列，text 用title/h1/正文。
    :param min_pages: 候选至少要出现在这么多个页面上。
        **默认 2** —— 只出现在一个页面的词多半是那页的专有名词，
        不是站点级的关键词机会。
    """
    seed_tokens: set[str] = set()
    for s in seeds:
        seed_tokens.update(tokenize(s))

    per_page = _page_tokens(pages)
    if not per_page:
        return []

    df: Counter[str] = Counter()
    df_url: dict[str, list[str]] = defaultdict(list)
    for url, toks in per_page.items():
        for t in toks:
            df[t] += 1
            if url not in df_url[t]:
                df_url[t].append(url)

    n_pages = len(per_page)

    # ---- 1. 共现挖掘 ----
    # 用 PMI 而非裸计数：计数会把「全站都在」的泛词排到前面
    # （「产品」「服务」这类词共现次数最高但最不值得做）。
    co_scores: dict[str, float] = defaultdict(float)
    co_with: dict[str, set[str]] = defaultdict(set)
    for url, toks in per_page.items():
        hits = toks & seed_tokens
        if not hits:
            continue
        for cand in toks - seed_tokens:
            if df[cand] < min_pages:
                continue
            joint = sum(1 for _, ts in per_page.items() if cand in ts and ts & hits)
            if joint == 0:
                continue
            p_cand = df[cand] / n_pages
            p_seed = len(hits) / n_pages
            p_joint = joint / n_pages
            pmi = math.log2(p_joint / (p_cand * p_seed)) if p_cand * p_seed else 0.0
            if pmi <= 0:
                continue
            co_scores[cand] += pmi
            co_with[cand].update(hits)

    cands: list[ExpansionCandidate] = []
    for term, score in co_scores.items():
        urls = df_url[term][:5]
        cands.append(
            ExpansionCandidate(
                term=term,
                score=float(score),
                source="cooccurrence",
                evidence_urls=urls,
                co_occurs_with=sorted(co_with[term])[:5],
                pages_seen=df[term],
            )
        )

    # ---- 2. 形态变体 ----
    # 分数低于共现：它不依赖语料，靠的是「改个说法往往同义」。
    existing = {c.term for c in cands} | seed_tokens
    for seed in seeds:
        for tok in tokenize(seed):
            variants: list[str] = []
            if _is_cjk(tok):
                variants = [p + tok for p in _CN_PREFIXES if p + tok not in existing]
            elif tok.isascii():
                for suf, stem in _EN_VARIANTS:
                    if tok.endswith(suf) and len(tok) > len(suf) + 2:
                        variants.append(tok[: -len(suf)] + stem)
            for v in variants[:3]:
                cands.append(
                    ExpansionCandidate(
                        term=v,
                        # 固定 0.5：形态变体没有语料支撑，给固定权重，
                        # 排不到有真实共现证据的词后面，但也不会垫底。
                        score=0.5,
                        source="morphology",
                        evidence_urls=[],
                        co_occurs_with=[seed],
                        pages_seen=0,
                    )
                )
                existing.add(v)

    cands.sort(key=lambda c: -c.score)
    return cands[:max_candidates]


def ngram_candidates(
    pages: Iterable[tuple[str, str]],
    *,
    n: int = 2,
    min_pages: int = 2,
    min_df_ratio: float = 0.1,
    max_candidates: int = 30,
) -> list[ExpansionCandidate]:
    """从标题里拼高频连续词组。

    ⚠️ 最容易产出垃圾的一路，所以门槛最严：
    **跨页面**出现 + 文档频率占比 ≥ ``min_df_ratio``。
    单页高频的词组（导航条「首页 关于我们」）全靠这条挡住。
    """
    titles: dict[str, str] = {}
    for url, text in pages:
        if text and text.strip():
            titles[url] = text.strip()

    if len(titles) < min_pages:
        return []

    grams: Counter[str] = defaultdict(set)
    for url, title in titles.items():
        toks = tokenize(title)
        for i in range(len(toks) - n + 1):
            if n == 2:
                gram = toks[i] + toks[i + 1]
            elif n == 3:
                gram = toks[i] + toks[i + 1] + toks[i + 2]
            else:
                gram = "".join(toks[i : i + n])
            if len(gram) < 2:
                continue
            grams[gram].add(url)

    out: list[ExpansionCandidate] = []
    for gram, urls in grams.items():
        df = len(urls)
        if df < min_pages or df / len(titles) < min_df_ratio:
            continue
        out.append(
            ExpansionCandidate(
                term=gram,
                score=round(df / len(titles), 4),
                source="ngram",
                evidence_urls=sorted(urls)[:5],
                pages_seen=df,
            )
        )
    out.sort(key=lambda c: -c.score)
    return out[:max_candidates]