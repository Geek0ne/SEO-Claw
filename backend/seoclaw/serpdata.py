"""SERP 数据入口：把关键词的搜索结果快照灌进 ``serp_snapshots``。

## 为什么单独补这一块

``serp_snapshots`` 表、``SerpRepository``、内容 Brief 里读 SERP 的那段代码
（``api/routes.py`` 的 brief 端点）**2026-10 之前就全就位了**，但和排名监测
当年一模一样的毛病：没有任何路径能把数据写进去。

后果不是「功能没做」，是**功能在静默装死**——brief 端点永远走
「竞品数据缺失」那条 caveat，Top10 共性永远是 ``available: False``，
而 README 写着「内容 Brief —— 基于 SERP 快照」。用户看到的是一份
只基于自己站点的 Brief，却以为它对照过竞品。

本模块补上入口，与 ``rankdata.py`` 同一套设计：

- CLI：``seoclaw serp-import <csv|json> --db seo.db``
- API：``POST /api/v1/sites/{id}/serp``（排名跟踪工具 / DataForSEO /
  SerpAPI 之类的 Provider 都可以往这送）
- 校验规则只有 ``result_from_fields`` 一份，CSV / JSON / API 共用。

## 数据格式

一条 SERP 记录 = 「某个词、某次抓取、某个位置上的结果」。
按 (关键词, 市场, 抓取时刻) 归组，一组就是一次 Top N 快照。

CSV 列名（大小写不敏感，认别名）：

| 字段 | 必填 | 别名 | 说明 |
|---|---|---|---|
| ``keyword`` | ✅ | query / term / 词 / 关键词 | 搜索词 |
| ``url`` | ✅ | link / page / address / 网址 | 结果页完整地址 |
| ``position`` | ✅ | rank / pos / 排名 | 该结果在第几位，**必须是正整数** |
| ``title`` | – | 标题 | Top10 标题共性统计的输入，缺了就只能算位次 |
| ``snippet`` | – | description / 描述 / 摘要 | 摘要原文 |
| ``captured_at`` | – | date / 抓取时间 / 日期 / timestamp | 抓取时刻；**整列留空 = 本文件算同一次抓取** |
| ``market`` | – | engine / 引擎 / 搜索引擎 | google / baidu，默认 google |
| ``features`` | – | 富结果 / rich / feature | 逗号分隔的富结果类型（paa/video/…） |

⚠️ **``position`` 不允许留空**。这与 ``rankdata`` 里「position 留空 = 当天
没数据」的口径刻意相反：排名表里留空是「不知道我方排第几」，而 SERP 表里
一条没有位次的记录根本不构成「搜索结果」——它会是哪个位置？填 0 还是
999 都会让 ``latest_for_keyword`` 的 Top N 排序出错。没位次就别导这条。

⚠️ **抓取时刻缺失时的归一**：没给 ``captured_at`` 的文件按**今天 00:00 UTC**
记为一次抓取。这样同一份 CSV 重跑是幂等的（当日回补），跨天重跑才会新增
一次快照——而不是每跑一次就多一堆「时间戳各差几秒」的伪历史。
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# CSV 列名归一：全小写去空格去 BOM 后匹配。别名按「谁最常用谁排前」维护。
_ALIASES: dict[str, tuple[str, ...]] = {
    "keyword": ("keyword", "query", "term", "搜索词", "关键词", "词"),
    "url": ("url", "link", "page", "address", "结果链接", "网址", "地址"),
    "position": ("position", "rank", "pos", "排名", "位次"),
    "title": ("title", "标题"),
    "snippet": ("snippet", "description", "摘要", "描述"),
    "captured_at": ("captured_at", "captured", "date", "timestamp", "抓取时间", "抓取日期", "日期"),
    "market": ("market", "engine", "search_engine", "搜索引擎", "引擎"),
    "features": ("features", "feature", "rich", "rich_results", "富结果"),
}

_REQUIRED = ("keyword", "url", "position")

#: 认得的市场。与 ``db.models.Market`` 的取值对齐 —— 词库建档的键是
#: (站点, 市场, 词)，这里少一个值就等于那一类 SERP 数据进不来。
_MARKETS = ("base", "google", "baidu", "cnh_eco")

#: 位次上限。超过这个数，说明数据源给的多半不是位次
#: （搜索量、竞品数都会被误填进来），宁可拒绝也别污染 Top N。
_MAX_POSITION = 1000


@dataclass
class SerpResult:
    """SERP 里的一条结果。"""

    url: str
    position: int
    title: str = ""
    snippet: Optional[str] = None
    features: list[str] = field(default_factory=list)


@dataclass
class SerpCapture:
    """一个词的一次抓取（一次 Top N 快照）。"""

    keyword: str
    market: str = "google"
    captured_at: Optional[datetime] = None
    results: list[SerpResult] = field(default_factory=list)


@dataclass
class ParseResult:
    captures: list[SerpCapture] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 逐行/逐条的跳过原因
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0


def _norm_header(name: str) -> str:
    return (name or "").strip().lower().lstrip("\ufeff")


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    """内部字段名 → CSV 原列名。认不出的列直接忽略（数据源常带多余列）。"""
    mapping: dict[str, str] = {}
    normed = {_norm_header(f): f for f in fieldnames}
    for target, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normed:
                mapping[target] = normed[alias]
                break
    return mapping


def _norm_market(raw: Any) -> str:
    val = _norm_header(str(raw)) if raw not in (None, "") else "google"
    return val or "google"


def parse_captured_at(raw: str) -> Optional[datetime]:
    """解析抓取时刻。空 → None（由调用方决定归一策略）。

    秒精度封顶（去掉微秒）：幂等键是 (关键词, 市场, 抓取时刻)，同一份
    文件重跑必须落进同一次抓取。带着微秒的时间戳来自 Provider 的本地
    时钟，第二次导出就变了，等于每次都新增一份历史。
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(
                f"抓取时间解析不了：{raw!r}（需要 ISO8601 或 YYYY-MM-DD[ HH:MM:SS]）"
            )
    if dt.tzinfo is None:
        # 无时区按 UTC 理解：SERP 数据源遍布多个国家，「本地时间」是歧义，
        # 而把歧义解成本机时区会让同一份文件在两台机器上进两个不同时刻。
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def _parse_features(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        # 一次全部分隔符一起切：数据源里 「paa, 视频; sitelink」 这种混用
        # 很常见，逐个分隔符轮流 split 再 break 会漏掉后面的。
        items = re.split(r"[|;；,，、]", str(raw))
    return [s.strip().lower() for s in items if s.strip()]


def result_from_fields(
    *,
    url: Any,
    position: Any,
    title: Any = "",
    snippet: Any = "",
    features: Any = None,
) -> SerpResult:
    """把原始字段构造成一条 SERP 结果——**校验规则唯一出处**。

    CSV / JSON / API 三个入口共用它。两套校验迟早会分叉，分叉后同一个值
    「CSV 能进、API 不能」（或反过来），排查起来是灾难。
    """
    url = (str(url) if url is not None else "").strip()
    if not url:
        raise ValueError("url 为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url 不是完整地址：{url!r}")

    pos_raw = str(position).strip() if position is not None else ""
    if not pos_raw:
        raise ValueError("position 为空：SERP 记录必须带位次（见模块文档）")
    try:
        pos_f = float(pos_raw)
    except ValueError:
        raise ValueError(f"position 不是整数位次：{position!r}") from None
    if not pos_f.is_integer():
        # SERP 位次是离散的「第几名」。1.5 这种值多半是把「平均排名」
        # （那是 rank_history 的量）错灌进了 SERP 表，静默取整会把它坐实成
        # 一个不存在的名次。
        raise ValueError(
            f"position 必须是整数位次：{position!r}（平均排名请导给 "
            "rank-import，那是日级时序表的量）"
        )
    pos = int(pos_f)
    if pos <= 0:
        raise ValueError(f"position 必须 > 0：{pos}")
    if pos > _MAX_POSITION:
        raise ValueError(
            f"position 超出合理范围：{pos} > {_MAX_POSITION}"
            "（位次不会这么大，多半是把搜索量/竞品数错填成了排名）"
        )

    snip = (str(snippet) if snippet is not None else "").strip()
    return SerpResult(
        url=url,
        position=pos,
        title=(str(title) if title is not None else "").strip(),
        snippet=snip or None,
        features=_parse_features(features),
    )


def capture_from_fields(
    *,
    keyword: Any,
    market: Any = None,
    captured_at: Any = "",
    results: Any = None,
) -> SerpCapture:
    """构造一次抓取（关键词 + 市场 + 时刻 + 结果列表），同样只有一份校验。"""
    term = (str(keyword) if keyword is not None else "").strip()
    if not term:
        raise ValueError("keyword 为空")
    mkt = _norm_market(market)
    if mkt not in _MARKETS:
        raise ValueError(
            f"market 不认识：{mkt!r}（认得的是 {' / '.join(_MARKETS)}）"
        )
    items = list(results or [])
    if not items:
        raise ValueError("这次抓取没有任何结果")
    return SerpCapture(
        keyword=term,
        market=mkt,
        captured_at=parse_captured_at(str(captured_at)) if captured_at not in (None, "") else None,
        results=items,
    )


def _warn_titleless(capture: SerpCapture, label: str, out: list[str]) -> None:
    """一次抓取里一条标题都没有 → Brief 的标题层共性算不出来。

    这不是错误（位次本身有用），但必须说出来：否则用户拿到一份
    ``serp_common.available: False`` 的 Brief，不知道是数据没导全。
    """
    if capture.results and not any(r.title for r in capture.results):
        out.append(
            f"{label}：{len(capture.results)} 条结果里一条标题都没有 —— "
            "内容 Brief 的「Top10 标题共性」会算不出来，只能给位次分布"
        )


def detect_format(text: str, filename: str = "") -> str:
    """这份导出是 JSON 还是 CSV —— 判定口径**只此一份**。

    CLI 有文件名（按 ``.json`` 后缀判），界面走 FileReader 拿到的是纯文本
    （没有后缀可问）。两边各写一遍迟早分叉，而判错一次的代价是把 JSON 喂给
    CSV 解析器 —— 它会指着 ``{"keyword": ...`` 那一行报「第 1 行缺列」，
    用户完全看不出是格式认错了。所以两条路都调这里。
    """
    if filename.lower().endswith(".json") or text.lstrip()[:1] in ("[", "{"):
        return "json"
    return "csv"


def parse_serp_csv(text: str) -> ParseResult:
    """解析 SERP CSV：一行一条结果，按 (词, 市场, 抓取时刻) 归成快照。

    ⚠️ 坏行**跳过并报行号**，不整批回滚：真实导出混一两行脏数据是常态
    （尤其是人工补过的表）；但坏行必须说出来，静默丢行会让「Top10 只剩
    7 条」看起来像「搜索结果就 7 条」。
    """
    result = ParseResult()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.errors.append("CSV 没有表头行，解析不了")
        return result

    mapping = _map_headers(list(reader.fieldnames))
    missing = [f for f in _REQUIRED if f not in mapping]
    if missing:
        result.errors.append(
            f"缺必需列：{'、'.join(missing)}（认得的别名见模块文档）"
        )
        return result

    # (关键词, 市场, 抓取时刻原串) → 该组已收的结果，保持插入顺序
    groups: dict[tuple[str, str, str], list[SerpResult]] = {}
    # Optional：整列都没有 captured_at 时留 None，交给 _default_captured_at()
    meta: dict[tuple[str, str, str], Optional[datetime]] = {}
    seen_urls: dict[tuple[str, str, str], set[str]] = {}

    for i, raw in enumerate(reader, start=2):  # 表头是第 1 行
        get = lambda key: raw.get(mapping.get(key, ""), "")  # noqa: E731
        term = str(get("keyword") or "").strip()
        mkt = _norm_market(get("market"))
        stamp_raw = str(get("captured_at") or "").strip()
        try:
            res = result_from_fields(
                url=get("url"),
                position=get("position"),
                title=get("title"),
                snippet=get("snippet"),
                features=get("features"),
            )
        except ValueError as exc:
            result.skipped += 1
            result.errors.append(f"第 {i} 行跳过：{exc}")
            continue

        if not term:
            result.skipped += 1
            result.errors.append(f"第 {i} 行跳过：keyword 为空")
            continue

        key = (term, mkt, stamp_raw)
        if stamp_raw:
            try:
                stamp = parse_captured_at(stamp_raw)
            except ValueError as exc:
                result.skipped += 1
                result.errors.append(f"第 {i} 行跳过：{exc}")
                continue
        else:
            stamp = None
        if key not in groups:
            groups[key] = []
            meta[key] = stamp
            seen_urls[key] = set()
        if res.url in seen_urls[key]:
            # 唯一约束是 (关键词, 时刻, url)，同一次抓取里重复 URL 只能留一条。
            # 静默留一条 vs 报错：报错——重复行意味着位次表本身有问题。
            result.skipped += 1
            result.errors.append(
                f"第 {i} 行跳过：{term} 的同一次抓取里 {res.url} 重复出现"
            )
            continue
        seen_urls[key].add(res.url)
        groups[key].append(res)

    for (term, mkt, stamp_raw), items in groups.items():
        try:
            cap = capture_from_fields(
                keyword=term, market=mkt, captured_at=stamp_raw, results=items
            )
        except ValueError as exc:
            result.skipped += len(items)
            result.errors.append(f"「{term}」这次抓取整组丢弃：{exc}")
            continue
        _warn_titleless(cap, f"「{term}」这次抓取", result.warnings)
        result.captures.append(cap)
    return result


def parse_serp_json(text: str) -> ParseResult:
    """解析 SERP JSON（Provider 导出 / 程序化上报常用形状）。

    认两种顶层形状：

    1. 一个对象：``{"market": "...", "captured_at": "...", "captures":
       [{"keyword": "...", "entries": [{...}]}]}``（``results`` /
       ``items`` 作为 ``captures`` 的别名）
    2. 一个数组：上面 ``captures`` 里那种元素直接铺平

    每条结果的字段名与 CSV 内部字段同名（url/position/title/snippet/features），
    ``entries`` 与 ``results`` 互为别名。
    """
    result = ParseResult()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        result.errors.append(f"JSON 解析失败：{exc}")
        return result

    if isinstance(data, dict):
        default_market = data.get("market")
        default_stamp = data.get("captured_at") or data.get("capturedAt") or ""
        blocks = data.get("captures") or data.get("results") or data.get("items")
        if blocks is None and data.get("keyword"):
            blocks = [data]  # 单对象即单次抓取，也接受
        if isinstance(data.get("entries"), list) and data.get("keyword"):
            blocks = [data]
    elif isinstance(data, list):
        default_market, default_stamp, blocks = None, "", data
    else:
        result.errors.append("JSON 顶层既不是对象也不是数组，认不了")
        return result

    if not isinstance(blocks, list) or not blocks:
        result.errors.append(
            "JSON 里没有 captures/results 数组——一个词的一次抓取就是一个元素"
        )
        return result

    for idx, block in enumerate(blocks, 1):
        if not isinstance(block, dict):
            result.skipped += 1
            result.errors.append(f"第 {idx} 组跳过：不是对象")
            continue
        raw_entries = block.get("entries")
        if not isinstance(raw_entries, list):
            raw_entries = block.get("results")
        # 收到这里是 list 或空列表：非 list（字符串、对象、null）都当「没给条目」，
        # 让下面的循环走「零条目 → warning」那条路，而不是在这里抛。
        entries: list[Any] = raw_entries if isinstance(raw_entries, list) else []
        items: list[SerpResult] = []
        for j, e in enumerate(entries, 1):
            if not isinstance(e, dict):
                result.skipped += 1
                result.errors.append(f"第 {idx} 组第 {j} 条跳过：不是对象")
                continue
            try:
                items.append(result_from_fields(
                    url=e.get("url"), position=e.get("position"),
                    title=e.get("title", ""), snippet=e.get("snippet", ""),
                    features=e.get("features"),
                ))
            except ValueError as exc:
                result.skipped += 1
                result.errors.append(f"第 {idx} 组第 {j} 条跳过：{exc}")
        try:
            cap = capture_from_fields(
                keyword=block.get("keyword") or block.get("query") or "",
                market=block.get("market") or default_market,
                captured_at=block.get("captured_at") or block.get("capturedAt") or default_stamp or "",
                results=items,
            )
        except ValueError as exc:
            result.skipped += len(items)
            result.errors.append(f"第 {idx} 组整组丢弃：{exc}")
            continue
        _warn_titleless(cap, f"第 {idx} 组「{cap.keyword}」", result.warnings)
        result.captures.append(cap)
    return result


def _default_captured_at() -> datetime:
    """没给抓取时刻时的那一次：今天 00:00 UTC。

    为什么按天而不是「现在」：幂等。同一份文件重跑必须落在同一次抓取上，
    否则每跑一次就多一簇时间戳只差几秒的伪历史，而
    ``latest_for_keyword`` 取的是「最新一次」——伪历史会把真历史挤下去。
    """
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def infer_domain(captures: list[SerpCapture]) -> Optional[str]:
    """从结果 URL 里推断站点域名。

    ⚠️ SERP 快照里**竞品占多数**，所以这里推断出来的多半是竞品域名而不是
    用户自己的站点。这个函数只用于「提示」，CLI 仍要求 --site 或库里已有
    的站点能对上——绝不因为「URL 里出现最多」就自动建一个站。
    """
    from collections import Counter
    from urllib.parse import urlparse

    hosts: Counter[str] = Counter()
    for cap in captures:
        for r in cap.results:
            host = urlparse(r.url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                hosts[host] += 1
    return hosts.most_common(1)[0][0] if hosts else None


async def ingest_captures(
    session: Any,
    site_id: int,
    captures: list[SerpCapture],
    *,
    captured_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """把解析好的快照幂等写进 ``serp_snapshots``，顺带建/复用关键词档案。

    返回写入摘要：新建了几条词、新插入/更新了几条结果。
    """
    from .db.repository import KeywordRepository, SerpRepository

    kw_repo = KeywordRepository(session)
    serp_repo = SerpRepository(session)
    fallback = captured_at or _default_captured_at()

    keywords_created = keywords_existing = inserted = updated = 0
    for cap in captures:
        kw = await kw_repo.get_by_term(site_id, cap.keyword, market=cap.market)
        if kw is None:
            kw = await kw_repo.create(
                site_id, cap.keyword, market=cap.market,
                is_tracked=True, tracked_at=fallback,
            )
            keywords_created += 1
        else:
            keywords_existing += 1
        stamp = cap.captured_at or fallback
        for r in cap.results:
            _, was_created = await serp_repo.upsert(
                keyword_id=kw.id,
                site_id=site_id,
                captured_at=stamp,
                market=cap.market,
                url=r.url,
                position=r.position,
                title=r.title,
                snippet=r.snippet,
                features=r.features,
            )
            inserted += 1 if was_created else 0
            updated += 0 if was_created else 1

    return {
        "keywords_created": keywords_created,
        "keywords_existing": keywords_existing,
        "inserted": inserted,
        "updated": updated,
        "captured_at": fallback.isoformat(),
    }
