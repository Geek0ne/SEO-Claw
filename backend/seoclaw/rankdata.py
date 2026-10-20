"""排名数据入口：把日级排名/流量数据灌进 ``rank_history``。

## 为什么单独补这一块

监测闭环的三件套其实早就写好了：``rank_history`` 表（日级时序）、
``RankHistoryRepository``（幂等 upsert）、``alerts.py``（跌落判断）。
但**没有任何路径能把数据灌进去**——闭环断在入口，用户看到的
「排名监测」是个只能看的空壳。本模块补上这个入口：

- CLI：``seoclaw rank-import <csv> --db seo.db``（批量导入）
- API：``POST /sites/{id}/rankings``（程序化接入，GSC API / BigQuery
  / 排名跟踪器都可以往这送）

## 数据格式（刻意与 GSC 网页版导出区分）

需要**日级**数据，列名认这些别名（大小写不敏感）：

| 字段 | 必填 | 别名 | 说明 |
|---|---|---|---|
| ``date`` | ✅ | day / 日期 | YYYY-MM-DD |
| ``url`` | ✅ | page / address / landing page | 页面完整地址 |
| ``position`` | – | rank / pos / average position | 当日平均排名，**拿不到就留空** |
| ``clicks`` | – | click | 当日点击 |
| ``impressions`` | – | impression / show | 当日曝光 |
| ``ctr`` | – | – | 0.1234 或 12.34% 两种写法都认 |
| ``keyword`` | – | query / 词 | 该日主要来源词（可选） |

⚠️ **Google Search Console 网页版导出的 CSV 不是这个格式**：它是
「所选时间区间」的聚合，没有日期列——区间聚合灌进日级表会把趋势图
和告警全部污染。要日级数据请走 GSC API / BigQuery 导出，或任何
按天出数的排名跟踪工具。硬灌聚合数据 = 用假时序画真趋势，比不画更糟。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

# 列名归一：全小写去空格后匹配。别名按「谁最常用谁排前」维护。
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "day", "日期", "统计日期"),
    "url": ("url", "page", "address", "landing page", "landing_page", "页面", "地址"),
    "position": ("position", "rank", "pos", "average position", "avg position", "平均排名", "排名"),
    "clicks": ("clicks", "click", "点击", "点击量"),
    "impressions": ("impressions", "impression", "show", "展示", "曝光", "曝光量"),
    "ctr": ("ctr", "点击率"),
    "keyword": ("keyword", "query", "term", "词", "关键词"),
}

_REQUIRED = ("date", "url")


@dataclass
class RankRow:
    """一行日级排名数据。position=None 表示「当天没有排名数据」——
    不是「排最后」。这个区分是 alerts.py 的判断前提，不能在入口抹平。"""

    date: date
    url: str
    position: Optional[float] = None
    clicks: int = 0
    impressions: int = 0
    ctr: Optional[float] = None
    keyword: Optional[str] = None


@dataclass
class ParseResult:
    rows: list[RankRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 逐行的跳过原因，行号可回溯
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


def _parse_date(raw: str) -> date:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期解析不了：{raw!r}（需要 YYYY-MM-DD）")


def _parse_float(raw: str) -> Optional[float]:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.endswith("%"):
        return float(raw[:-1]) / 100.0
    return float(raw)


def _parse_int(raw: str) -> int:
    raw = (raw or "").strip()
    return int(float(raw)) if raw else 0


def row_from_fields(
    *,
    date_raw: str,
    url: str,
    position: Any = None,
    clicks: Any = 0,
    impressions: Any = 0,
    ctr: Any = None,
    keyword: str = "",
) -> RankRow:
    """把原始字段构造成 RankRow，校验规则唯一出处。

    CSV 与 API 入口共用它：两套校验迟早分叉，分叉后同一个值
    「CSV 能进、API 不能」（或反过来），排查起来是灾难。
    拿不到的 position 留 None —— 不是 0，不是 999。
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("url 为空")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url 不是完整地址：{url!r}")

    ctr_val = _parse_float(str(ctr)) if ctr not in (None, "") else None
    if ctr_val is not None and not 0 <= ctr_val <= 1:
        raise ValueError(f"ctr 超出 [0,1]：{ctr_val}（百分比请带 % 或换算成小数）")

    pos_raw = str(position).strip() if position is not None else ""
    pos_val = _parse_float(pos_raw) if pos_raw else None
    if pos_val is not None and pos_val <= 0:
        raise ValueError(f"position 必须 > 0：{pos_val}（没数据请留空）")

    return RankRow(
        date=_parse_date(str(date_raw)),
        url=url,
        position=pos_val,
        clicks=_parse_int(str(clicks)),
        impressions=_parse_int(str(impressions)),
        ctr=ctr_val,
        keyword=(keyword or "").strip() or None,
    )


def parse_rank_csv(text: str) -> ParseResult:
    """解析日级排名 CSV。

    ⚠️ 坏行**跳过并报行号**，不整批回滚：真实导出里混一两行脏数据是
    常态，为此丢掉整份 3000 行的导入是过度反应；但坏行必须说出来，
    静默丢行会让「少了一天数据」看起来像「那天没排名」。
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
            f"缺必需列：{'、'.join(missing)}（认得的别名见模块文档；"
            "GSC 网页版导出的区间聚合 CSV 不适用，请用日级数据源）"
        )
        return result

    for i, raw in enumerate(reader, start=2):  # 表头是第 1 行
        get = lambda key: raw.get(mapping.get(key, ""), "")  # noqa: E731
        try:
            result.rows.append(row_from_fields(
                date_raw=get("date"),
                url=get("url"),
                position=get("position"),
                clicks=get("clicks"),
                impressions=get("impressions"),
                ctr=get("ctr"),
                keyword=get("keyword"),
            ))
        except ValueError as exc:
            result.skipped += 1
            result.errors.append(f"第 {i} 行跳过：{exc}")
    return result


def infer_domain(rows: list[RankRow]) -> Optional[str]:
    """从 URL 里推断站点域名：多数 URL 的 host（剥 www.）就是它。"""
    from collections import Counter
    from urllib.parse import urlparse

    hosts = Counter()
    for r in rows:
        host = urlparse(r.url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            hosts[host] += 1
    return hosts.most_common(1)[0][0] if hosts else None


async def ingest_rows(session, site_id: int, rows: list[RankRow]) -> dict[str, Any]:
    """把解析好的行幂等写进 rank_history。返回写入摘要。"""
    from .db.repository import RankHistoryRepository

    repo = RankHistoryRepository(session)
    written = 0
    for row in rows:
        await repo.upsert_day(
            site_id,
            row.url,
            row.date,
            position=row.position,
            clicks=row.clicks,
            impressions=row.impressions,
            ctr=row.ctr,
        )
        written += 1
    return {"upserted": written}
