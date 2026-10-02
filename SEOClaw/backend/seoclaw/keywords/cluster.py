"""关键词聚类：把语义相近的词归到一组。

## 为什么是词形聚类而不是语义聚类

PLAN 原本写的是 pgvector 语义聚类。但那需要 embedding，
**embedding 同样要API key**。没有 key 就只能等，或者假装做了。

这里选一条**不依赖凭据、结果可复现**的路：
字符 n-gram TF-IDF + 余弦相似度 + 并查集。

它当然不是语义理解，但在这个场景里够用：
- 「seo优化」和「SEO优化技巧」共享 `se`/`eo`/`优化` 等 n-gram → 聚到一起
- 「seo优化」和「wordpress建站」共享很少 → 不聚

⚠️ 而且它的输出**可核对**：两词被聚到一起时，会给出**共享了哪些 n-gram**
作为证据。用户点开一看就知道该不该合并。「语义相似度 0.87」谁也核对不了。

## 什么时候必须换语义聚类

英文长尾词（拼写差异大、无共同字面）会聚不到一起——
比如 "affordable web design" 和 "cheap website design"。
这类需要 embedding。本模块的 :func:`cluster` 预留了``embed_fn`` 参数，
拿到 key 后接入即可，接口不变。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

# 聚类粒度：2~3 字/字符的片段。对中文够用（"优化" -> 优化），
# 对英文也能把 "design" 和 "designer" 拉近一点。
_NGRAM_RANGE = (2, 3)


def _char_ngrams(text: str, lo: int = 2, hi: int = 3) -> list[str]:
    """字符 n-gram。

    英文小写后去空格：词序在搜索词里意义不大，
    "web design" 和 "design web" 应该是同一个簇。
    """
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not t:
        return []
    out: list[str] = []
    for n in range(lo, hi + 1):
        if len(t) < n:
            continue
        out.extend(t[i : i + n] for i in range(len(t) - n + 1))
    return out


@dataclass
class KeywordCluster:
    cluster_id: int
    terms: list[str] = field(default_factory=list)
    #: 代表词：成员里最长的那个（通常是信息量最大的完整短语）。
    representative: str = ""

    def as_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "representative": self.representative,
            "terms": self.terms,
            "size": len(self.terms),
        }


@dataclass
class MergeEvidence:
    """两个词被聚到一起的依据。**必须可核对**——不给数字了事。"""

    a: str
    b: str
    similarity: float
    shared_ngrams: list[str]

    def as_dict(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "similarity": round(self.similarity, 4),
            "shared_ngrams": self.shared_ngrams,
        }


def _tfidf_vectors(
    docs: dict[str, list[str]],
) -> dict[str, dict[str, float]]:
    """TF-IDF + L2 归一化。返回 ``{term: {ngram: weight}}``。

    IDF 用 ``log((N+1)/(df+1)) + 1``（平滑版）：某个 n-gram 在所有词里
    都出现时权重趋近 0——那种片段没有区分度（"的"、"com"）。
    """
    n = len(docs)
    df: Counter[str] = Counter()
    for grams in docs.values():
        df.update(set(grams))
    vecs: dict[str, dict[str, float]] = {}
    for term, grams in docs.items():
        tf = Counter(grams)
        vec = {
            g: (c / len(grams)) * (math.log((n + 1) / (df[g] + 1)) + 1)
            for g, c in tf.items()
        }
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vecs[term] = {g: v / norm for g, v in vec.items()}
    return vecs


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """余弦相似度。向量已 L2 归一化，所以交集内积就是余弦。"""
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(g, 0.0) for g, w in a.items())


def shared_ngrams(a: dict[str, float], b: dict[str, float], top: int = 6) -> list[str]:
    """取权重乘积最高的若干共享 n-gram 作为合并依据。

    只给「哪些片段相同」，不给一个孤零零的分数——
    用户能自己判断这个相似度是不是合理。
    """
    pairs = [(w * b.get(g, 0.0), g) for g, w in a.items() if g in b]
    pairs.sort(reverse=True)
    return [g for _, g in pairs[:top]]


def cluster(
    terms: Sequence[str],
    *,
    threshold: float = 0.35,
    max_cluster_size: int = 25,
    embed_fn: Optional[Callable[[Sequence[str]], list[list[float]]]] = None,
) -> tuple[list[KeywordCluster], list[MergeEvidence]]:
    """把词聚成簇。

    :param threshold: 余弦相似度阈值。低于它就不合并。
        调高更保守（簇更多更细），调低更激进（容易把无关词并一起）。
    :param embed_fn: 预留接口。传入后走语义聚类（需要 embedding API），
        没有 key 时保持 None，走词形聚类。接口不变，将来接入不影响调用方。
    :returns: ``(簇列表, 合并依据列表)``

    ⚠️ 用并查集而不是单趟遍历合并：单趟会有顺序依赖——
    A~B 合了、B~C 没合（因为 B 已经被 A 吸收），A 和 C 就永远合不到一起。
    并查集让「两两可达」成为最终结果，与输入顺序无关。
    """
    uniq = [t for t in dict.fromkeys(t for t in terms if t and t.strip())]
    if not uniq:
        return [], []

    if embed_fn is not None:
        # 预留：拿到 embedding key 后在这里换实现，调用方签名不变。
        raise NotImplementedError(
            "语义聚类需要 embedding API key。当前实现为词形聚类（离线可用）。"
            "接入方式：传 embed_fn=lambda terms: your_client.embed(terms)。"
        )

    docs = {t: _char_ngrams(t, *_NGRAM_RANGE) for t in uniq}
    vecs = _tfidf_vectors(docs)

    parent: dict[str, str] = {t: t for t in uniq}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # 路径压缩
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    evidence: list[MergeEvidence] = []
    for i, a in enumerate(uniq):
        for b in uniq[i + 1 :]:
            sim = cosine(vecs[a], vecs[b])
            if sim >= threshold:
                union(a, b)
                evidence.append(
                    MergeEvidence(
                        a=a,
                        b=b,
                        similarity=sim,
                        shared_ngrams=shared_ngrams(vecs[a], vecs[b]),
                    )
                )

    buckets: dict[str, list[str]] = {}
    for t in uniq:
        buckets.setdefault(find(t), []).append(t)

    clusters: list[KeywordCluster] = []
    for cid, (root, members) in enumerate(
        sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])), start=1
    ):
        members.sort(key=lambda s: (-len(s), s))
        # ⚠️ 超大簇几乎一定是阈值太低导致的（所有词都像），
        # 宁可拆开也不要给用户一个「全都在一簇」的结果。
        if len(members) > max_cluster_size:
            for m in members:
                clusters.append(
                    KeywordCluster(cluster_id=len(clusters) + 1, terms=[m], representative=m)
                )
            continue
        clusters.append(
            KeywordCluster(
                cluster_id=len(clusters) + 1,
                terms=members,
                # 代表词取最长者：最长通常是最完整的表达。
                representative=members[0],
            )
        )
    return clusters, evidence