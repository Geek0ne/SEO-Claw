"""关键词扩展与聚类。

分层是刻意的，两层都不需要任何 API key：

- :mod:`.expand` —— 从站内语料挖候选词，给**可核对的证据**（页面 URL 列表）。
- :mod:`.cluster` —— 词形聚类（字符 n-gram TF-IDF + 余弦 + 并查集），
  给出**可核对的合并依据**（共享了哪些 n-gram）。

PLAN 原本写的是 pgvector 语义聚类，但 embedding 同样需要 API key。
这里的选择是：**先把离线可复现的部分做扎实，把语义那半边留成
``cluster(..., embed_fn=...)`` 的接口位**——拿到 key 后接入不影响调用方。
"""

from .cluster import (
    KeywordCluster,
    MergeEvidence,
    cluster,
    cosine,
    shared_ngrams,
)
from .expand import ExpansionCandidate, expand, ngram_candidates, tokenize

__all__ = [
    "ExpansionCandidate",
    "expand",
    "ngram_candidates",
    "tokenize",
    "KeywordCluster",
    "MergeEvidence",
    "cluster",
    "cosine",
    "shared_ngrams",
]