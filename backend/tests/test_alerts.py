"""排名跌幅告警的判断逻辑。

⚠️ 单独成文件是因为它**不碰 DB**，所以能离线测边界。告警逻辑天生
容易写错（阈值、None、噪声），绑在端到端里就只能测「该报时有没有报」，
而「**本该沉默时有没有多嘴**」—— 那一半恰恰测不到，且才是会毁掉信任的一半。
"""

from seoclaw.alerts import RankPoint, detect_rank_drops


def _series(url: str, positions: list[float | None], imps: int = 100):
    return url, [
        RankPoint(date=f"2026-10-{d:02d}", position=p, impressions=imps)
        for d, p in enumerate(positions, start=1)
    ]


def test_reports_a_real_drop():
    """10 → 22，确实跌了，该报。"""
    by_url = dict([_series("/a", [10, 11, 12, 22])])
    alerts = detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.url == "/a"
    assert a.drop == 12.0
    assert "10.0" in a.message and "22.0" in a.message


def test_stays_silent_on_tiny_wobble():
    """10 → 12，波动而已。⚠️ 这条是「沉默」侧的关键用例：
    按天盯排名的人若每跌 2 名收一条提醒，一周七条然后全部忽略 ——
    告警一多就不叫告警了。"""
    by_url = dict([_series("/a", [10, 11, 10, 12])])
    assert detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4) == []


def test_stays_silent_on_improvement():
    """排名数字**越小越靠前**，所以涨名次 = drop 为负，必须沉默。"""
    by_url = dict([_series("/a", [30, 25, 20, 12])])
    assert detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4) == []


def test_stays_silent_on_low_impression_noise():
    """曝光 1 次时 40→45 是随机波动，不是下滑。拿它报警等于制造噪音。"""
    by_url = dict([_series("/a", [40, 42, 41, 45], imps=1)])
    assert detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4) == []


def test_none_position_is_not_treated_as_worst():
    """⚠️ position=None 是「当天没有排名数据」，不是「排最后」。

    拿 None 去算差值会得到 None，然后 if 判断悄悄走 False —— 函数返回
    空列表，看起来像「没有跌落」，其实是**「无法判断」**。这两种在
    用户眼里是一样的空白，但含义完全不同。"""
    by_url = dict([_series("/a", [None, 12, 13, 22])])
    alerts = detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4)
    assert alerts == [], "首日没有排名数据时不该下结论"

    # ⚠️ 顺带锁住另一半：None 落在**中间**时，首尾都有效，结论就该成立 ——
    # 某天没数据不等于这页排名没法判断。第一版我把 None 放中间还断言
    # 返回空，是测试自己写错了，代码是对的。
    mid = dict([_series("/b", [10, None, 12, 22])])
    assert len(detect_rank_drops(mid, min_drop=5.0, min_impressions=10, min_days=4)) == 1


def test_needs_enough_days():
    """只有两天数据时，「第一天 vs 最后一天」只是两天的偶然差值。"""
    by_url = dict([_series("/a", [10, 20])])
    assert detect_rank_drops(by_url, min_drop=5.0, min_impressions=10, min_days=4) == []


def test_sorts_worst_drop_first():
    """用户先看最该看的那个。"""
    a = dict([_series("/small", [10, 11, 12, 16])])  # 掉 6 名，够门槛
    b = dict([_series("/big", [10, 20, 30, 45])])
    alerts = detect_rank_drops({**a, **b}, min_drop=5.0, min_impressions=10, min_days=4)
    assert [x.url for x in alerts] == ["/big", "/small"]


def test_unsorted_input_gives_same_answer():
    """喂乱序也该得同一结论 —— 排序口径只留一处，别处各排一次必有一处错。"""
    pts = list(reversed(dict([_series("/a", [10, 11, 12, 22])])["/a"]))
    alerts = detect_rank_drops({"/a": pts}, min_drop=5.0, min_impressions=10, min_days=4)
    assert len(alerts) == 1 and alerts[0].drop == 12.0


def test_empty_site_returns_empty_list():
    """空输入是合法结论，不是失败。"""
    assert detect_rank_drops({}) == []


def test_alert_key_is_stable_across_score_changes():
    """⚠️ 告警标识**不得**包含分数与曝光量。

    同一场跌落每被查一次，from_position/to_position 可能因为窗口滑动而
    略有不同。若把它们塞进标识，用户标记过一次「看过了」，下一次窗口一滑
    就被算成**另一场**跌落，于是同件事反复提醒 —— 而加「已看过」本来
    就是为了解决这个。
    """
    a = detect_rank_drops(
        dict([_series("/a", [10, 11, 12, 22])]), min_drop=5.0, min_impressions=10,
        min_days=4,
    )[0]
    # 同样的起止日、但窗口里多了一天（首尾分数被重新算过）
    pts = list(_series("/a", [10, 11, 12, 13, 22])[1])
    b = detect_rank_drops({"/a": pts}, min_drop=5.0, min_impressions=10, min_days=4)[0]
    assert a.key != b.key, "起止日不同就应该是不同的场次"
    assert "/a|2026-10-01|2026-10-04" == a.key, "key 应只由 url + 起止日组成"


def test_alert_key_contains_no_score():
    """反向断言：key 里不出现数字形式的分数/曝光量。"""
    a = detect_rank_drops(
        dict([_series("/a", [10, 11, 12, 22], imps=12345)]),
        min_drop=5.0, min_impressions=10, min_days=4,
    )[0]
    assert "12345" not in a.key
    assert a.key.count("|") == 2
