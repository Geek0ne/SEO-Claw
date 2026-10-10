"""免费额度：2000 页/月，按页不按次。

## 为什么按页不按次

成本与**抓取的页数**成正比，与「扫了几次」无关：扫 2 次 5000 页比
扫 20 次 100 页贵得多。按次数限制会挡住还没体验到价值的用户
（他才扫了 2 次），却挡不住真正贵的用法。

## ⚠️ 自部署单机不计量

部署者决定：「目前是灰度测试阶段，不限制使用（单机自用）」。
所以**只在开鉴权（``SEO_CLAW_AUTH=on``，即 SaaS 模式）时才拦**。
单机模式返回 ``None`` 表示「不限」而不是「额度无限大」—— 这两者在
语义上不同，前者是产品决定，后者是配置值。
"""

from __future__ import annotations

import calendar
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from ..db import models as m

DEFAULT_FREE_PAGES = 2000


def free_pages_per_month() -> Optional[int]:
    """本月的免费页数上限。``None`` = 不限量。"""
    raw = os.getenv("SEO_CLAW_FREE_PAGES", "").strip()
    if not raw:
        return DEFAULT_FREE_PAGES
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_FREE_PAGES
    return None if n <= 0 else n


def month_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    y, mo = now.year, now.month
    start = datetime(y, mo, 1, tzinfo=timezone.utc)
    end_day = calendar.monthrange(y, mo)[1]
    end = datetime(y, mo, end_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


async def monthly_pages(session, owner: str) -> int:
    """该归属本月已用页数。

    ⚠️ 刻意用 ``SUM`` 重算而不是读一个累加列 —— 计费数字必须能被
    随时复算，口径分叉之后没人知道该信哪个。
    """
    start, end = month_bounds()
    stmt = (
        select(func.coalesce(func.sum(m.UsageEvent.quantity), 0))
        .select_from(m.UsageEvent)
        .join(m.Site, m.Site.id == m.UsageEvent.site_id)
        .where(
            m.Site.owner == owner,
            m.UsageEvent.kind == "pages_crawled",
            m.UsageEvent.at >= start,
            m.UsageEvent.at <= end,
        )
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def enforce(session, owner: str, *, would_use: int, enabled: bool) -> dict:
    """扫描前拦一道。返回本月的用量快照。

    :param enabled: 是否处于计量模式（= SaaS）。单机模式直接放行。
    """
    limit = free_pages_per_month() if enabled else None
    if limit is None:
        return {"used": 0, "limit": None, "enforced": False}
    used = await monthly_pages(session, owner)
    if used + would_use > limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"本月免费额度已用完：{used}/{limit} 页。"
                f"这次还需 {would_use} 页。"
                "额度按自然月重置，下个月 1 号自动恢复。"
            ),
        )
    return {"used": used, "limit": limit, "enforced": True}
