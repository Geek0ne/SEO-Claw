"""排名数据入口（rankdata）测试。

只测解析与校验，不碰 DB：入口的职责是「把脏数据挡在门外、把好数据
说清楚」，这层的错误比 DB 层的错误便宜得多。
"""

from __future__ import annotations

from datetime import date

import pytest

from seoclaw.rankdata import (
    infer_domain,
    parse_rank_csv,
    row_from_fields,
)


def test_parse_basic_headers_and_aliases():
    text = (
        "Page,Date,Average Position,Clicks,Impressions,CTR,Query\n"
        "https://demo.test/a,2026-10-01,12.5,10,200,5%,登山鞋\n"
        "https://demo.test/b,2026-10-01,,,,,\n"
    )
    parsed = parse_rank_csv(text)

    assert parsed.errors == []
    assert len(parsed.rows) == 2
    a, b = parsed.rows
    assert a.url == "https://demo.test/a"
    assert a.date == date(2026, 10, 1)
    assert a.position == 12.5
    assert a.clicks == 10 and a.impressions == 200
    assert a.ctr == pytest.approx(0.05)  # 百分号写法归一成小数
    assert a.keyword == "登山鞋"
    # 拿不到的数字留 None/0，不硬凑
    assert b.position is None and b.ctr is None and b.clicks == 0


def test_bad_rows_skipped_with_line_numbers():
    text = (
        "date,url,position\n"
        "2026-10-01,https://demo.test/a,5\n"
        "not-a-date,https://demo.test/b,6\n"
        "2026-10-02,not-a-url,7\n"
        "2026-10-03,https://demo.test/d,0\n"
    )
    parsed = parse_rank_csv(text)

    assert len(parsed.rows) == 1  # 好行照常入库
    assert parsed.skipped == 3
    assert any("第 3 行" in e for e in parsed.errors)  # 行号可回溯
    assert any("position" in e for e in parsed.errors)


def test_gsc_web_export_rejected_because_no_date_column():
    """GSC 网页版导出是区间聚合——灌进日级表等于用假时序画真趋势。"""
    text = (
        "Top pages,Clicks,Impressions,CTR,Position\n"
        "https://demo.test/a,10,200,5%,12.5\n"
    )
    parsed = parse_rank_csv(text)

    assert parsed.rows == []
    assert any("date" in e for e in parsed.errors)
    assert any("日级" in e for e in parsed.errors)


def test_missing_file_header_says_so():
    parsed = parse_rank_csv("")
    assert parsed.rows == []
    assert parsed.errors and "表头" in parsed.errors[0]


def test_ctr_out_of_range_rejected():
    with pytest.raises(ValueError, match="ctr"):
        row_from_fields(date_raw="2026-10-01", url="https://demo.test/a", ctr=12.5)


def test_position_zero_means_no_data_not_rank_zero():
    with pytest.raises(ValueError, match="position"):
        row_from_fields(date_raw="2026-10-01", url="https://demo.test/a", position=0)


def test_date_formats_and_bad_date():
    assert row_from_fields(date_raw="2026/10/01", url="https://demo.test/a").date == date(2026, 10, 1)
    assert row_from_fields(date_raw="20261001", url="https://demo.test/a").date == date(2026, 10, 1)
    with pytest.raises(ValueError, match="日期"):
        row_from_fields(date_raw="10/01/2026", url="https://demo.test/a")


def test_infer_domain_prefers_majority_host():
    rows = [
        row_from_fields(date_raw="2026-10-01", url="https://www.demo.test/a"),
        row_from_fields(date_raw="2026-10-01", url="https://demo.test/b"),
        row_from_fields(date_raw="2026-10-01", url="https://demo.test/c"),
        row_from_fields(date_raw="2026-10-01", url="https://other.test/x"),
    ]
    assert infer_domain(rows) == "demo.test"  # www. 归一后再计数
