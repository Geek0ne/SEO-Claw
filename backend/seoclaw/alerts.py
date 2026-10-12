"""排名监控：从 ``rank_history`` 里算出「该提醒用户」的跌落。

⚠️ 这个模块只做**判断**，不碰 DB、不发通知。这样它能脱离数据库单测
——而告警逻辑天生容易写错（各种阈值、各种边界），绑在 DB 上就只能靠
端到端试，而端到端试不出「本该沉默时有没有多嘴」。

判断与通知严格分开：判断错会打扰用户，通知错只是慢一点。所以
notify 之前一定是这里先算对了。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, slots=True)
class RankPoint:
    """一天的排名观测。

    ``position`` 为 None 表示**当天没有排名数据**（没进前 100 / GSC 未覆盖），
    与「排第 50 名」是完全不同的两件事 —— 后者是有数据，只是差。
    """

    date: str
    position: Optional[float]
    impressions: int = 0
    clicks: int = 0


@dataclass(frozen=True, slots=True)
class RankDropAlert:
    url: str
    #: 稳定标识「这一场跌落」，用于「已看过」标记。
    from_position: float
    to_position: float
    drop: float
    from_date: str
    to_date: str
    #: 人话版结论，直接可发给用户。**不给**这个，通知里塞一堆数字
    #: 等于让用户自己解读——而用户看不出「10→20」是好是坏。
    message: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """同一场跌落的稳定标识：URL + 起止日。

        ⚠️ 刻意**不含**分数与曝光量：同一场跌落每被查一次，算出来的
        from_position/to_position 可能因为窗口滑动而略有不同。若把它们
        塞进标识，用户标记过一次「看过了」，下一次窗口一滑就算成
        **另一场**跌落，于是同件事反复提醒 —— 那正是加「已看过」
        本来要解决的问题。标识只能由「这件事本身」决定。
        """
        return f"{self.url}|{self.from_date}|{self.to_date}"


def detect_rank_drops(
    series_by_url: dict[str, list[RankPoint]],
    *,
    min_drop: float = 5.0,
    min_impressions: int = 10,
    min_days: int = 4,
) -> list[RankDropAlert]:
    """挑出「排名确实跌了」的 URL。

    :param min_drop: 掉了多少名才算事。小波动天天有，按天盯排名的人
        若每跌 2 名就收一条提醒，一周会收到七条，然后全部忽略 ——
        **告警一多就不叫告警了**。
    :param min_impressions: 两天都要有这个曝光量才敢比。曝光 1 次时
        排名从 40 跳到 45 是随机波动，不是下滑；拿它报警等于制造噪音。
    :param min_days: 至少要有这么多个观测点，否则「第一天 vs 最后一天」
        只是两天的偶然差值。
    """
    alerts: list[RankDropAlert] = []
    for url, pts in series_by_url.items():
        pts = sorted(pts, key=lambda p: p.date)
        if len(pts) < min_days:
            continue

        head, tail = pts[0], pts[-1]
        # None 是「没有排名数据」，不是「排最后」。
        # 拿 None 去算差值会得到 None，然后 if 判断悄悄走 False ——
        # 整个函数返回空列表，看起来像「没有跌落」，其实是「无法判断」。
        if head.position is None or tail.position is None:
            continue
        if head.impressions < min_impressions or tail.impressions < min_impressions:
            continue

        drop = tail.position - head.position  # 排名数字越大越靠后
        if drop < min_drop:
            continue

        alerts.append(
            RankDropAlert(
                url=url,
                from_position=head.position,
                to_position=tail.position,
                drop=drop,
                from_date=head.date,
                to_date=tail.date,
                message=(
                    f"{url} 的排名从第 {head.position:.1f} 名跌到第 "
                    f"{tail.position:.1f} 名（{head.date} → {tail.date}，"
                    f"掉了 {drop:.0f} 名）"
                ),
                evidence={
                    "min_impressions": min_impressions,
                    "days_observed": len(pts),
                    "from_impressions": head.impressions,
                    "to_impressions": tail.impressions,
                },
            )
        )
    alerts.sort(key=lambda a: a.drop, reverse=True)
    return alerts
