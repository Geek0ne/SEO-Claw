"""SERP 数据入口（serpdata）测试。

与 ``test_rankdata.py`` 同样只测解析与校验，不碰 DB —— 入口层的职责是
「把脏数据挡在门外、把好数据说清楚」。落库幂等在 ``test_db.py``，
端到端在 ``test_api.py``（POST /serp → GET /serp → Brief 吃到竞品数据）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from seoclaw.serpdata import (
    capture_from_fields,
    infer_domain,
    parse_captured_at,
    parse_serp_csv,
    parse_serp_json,
    result_from_fields,
)

# --------------------------------------------------------------------------
# 单条结果的校验
# --------------------------------------------------------------------------


def test_result_requires_full_url_and_positive_position():
    r = result_from_fields(url="https://demo.test/a", position="3", title="A")
    assert (r.url, r.position, r.title) == ("https://demo.test/a", 3, "A")

    with pytest.raises(ValueError, match="完整地址"):
        result_from_fields(url="demo.test/a", position=1)
    with pytest.raises(ValueError, match="position"):
        result_from_fields(url="https://demo.test/a", position=0)


def test_position_must_not_be_blank():
    """⚠️ 与 rankdata 相反：那里的 position 留空是「当天没数据」，这里留空
    的记录根本不构成一条搜索结果——填 0 或 999 都会污染 Top N 排序。"""
    with pytest.raises(ValueError, match="position 为空"):
        result_from_fields(url="https://demo.test/a", position="")


def test_absurd_position_rejected_as_wrong_column():
    """位次大到四位数，多半是把搜索量/竞品数错填成了排名。"""
    with pytest.raises(ValueError, match="超出合理范围"):
        result_from_fields(url="https://demo.test/a", position=123456)


def test_features_accept_list_and_separators():
    assert result_from_fields(
        url="https://demo.test/a", position=1, features=["PAA", "video"]
    ).features == ["paa", "video"]
    assert result_from_fields(
        url="https://demo.test/a", position=1, features="paa, 视频; sitelink"
    ).features == ["paa", "视频", "sitelink"]
    assert result_from_fields(url="https://demo.test/a", position=1).features == []


# --------------------------------------------------------------------------
# 抓取时刻
# --------------------------------------------------------------------------


def test_captured_at_formats_and_naive_treated_as_utc():
    assert parse_captured_at("2026-10-21") == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert parse_captured_at("2026-10-21 09:30") == datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
    assert parse_captured_at("2026-10-21T09:30:00Z") == datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)
    # 微秒被抹掉：幂等键里带时间戳，留着微秒会让同一份文件每次重跑都新增一次抓取
    assert parse_captured_at("2026-10-21T09:30:00.123456Z").microsecond == 0

    with pytest.raises(ValueError, match="抓取时间"):
        parse_captured_at("21/10/2026")


def test_capture_market_is_validated():
    with pytest.raises(ValueError, match="market"):
        capture_from_fields(keyword="seo 工具", market="bing", results=[
            result_from_fields(url="https://demo.test/a", position=1)
        ])
    with pytest.raises(ValueError, match="没有任何结果"):
        capture_from_fields(keyword="seo 工具", results=[])


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

CSV_OK = (
    "Query,Link,Position,Title,Snippet,Date,Engine,Features\n"
    "seo 工具,https://a.test/1,1,工具 A,介绍 A,2026-10-21,google,paa|video\n"
    "seo 工具,https://b.test/2,2,工具 B,介绍 B,2026-10-21,google,\n"
    "登山鞋,https://c.test/3,1,登山鞋推荐,,,,\n"
)


def test_csv_groups_rows_into_captures():
    parsed = parse_serp_csv(CSV_OK)
    assert parsed.errors == [] and parsed.skipped == 0
    assert len(parsed.captures) == 2, "按 (词, 市场, 抓取时刻) 归组"
    seo, shoes = parsed.captures
    assert seo.keyword == "seo 工具" and len(seo.results) == 2
    assert seo.results[0].features == ["paa", "video"]
    assert seo.captured_at == datetime(2026, 10, 21, tzinfo=timezone.utc)
    # 没给时刻/引擎的词：一次抓取、时刻留空由入口归一，市场默认 google
    assert shoes.captured_at is None and shoes.market == "google"


def test_csv_bad_rows_skipped_with_line_numbers():
    text = (
        "keyword,url,position\n"
        "seo 工具,https://a.test/1,1\n"
        "seo 工具,https://b.test/2,\n"          # 缺位次
        "seo 工具,not-a-url,3\n"                 # URL 不是完整地址
        ",https://d.test/4,4\n"                  # 缺关键词
        "seo 工具,https://e.test/5,2\n"
    )
    parsed = parse_serp_csv(text)
    assert parsed.skipped == 3
    assert len(parsed.captures) == 1 and len(parsed.captures[0].results) == 2
    assert any("第 3 行" in e for e in parsed.errors)
    assert any("第 4 行" in e for e in parsed.errors)
    assert any("第 5 行" in e for e in parsed.errors)


def test_csv_duplicate_url_in_one_capture_is_reported():
    """唯一键是 (词, 时刻, URL)。静默留一条会让「Top10 只有 9 条」看不出来。"""
    text = (
        "keyword,url,position,captured_at\n"
        "seo 工具,https://a.test/1,1,2026-10-21\n"
        "seo 工具,https://a.test/1,7,2026-10-21\n"
    )
    parsed = parse_serp_csv(text)
    assert parsed.skipped == 1
    assert any("重复出现" in e for e in parsed.errors)
    assert len(parsed.captures[0].results) == 1


def test_csv_missing_required_column_names_it():
    parsed = parse_serp_csv("keyword,url\nseo 工具,https://a.test/1\n")
    assert parsed.captures == []
    assert parsed.errors and "position" in parsed.errors[0]


def test_empty_csv_says_no_header():
    parsed = parse_serp_csv("")
    assert parsed.captures == [] and "表头" in parsed.errors[0]


def test_capture_without_titles_warns_instead_of_failing():
    """位次齐了但一条标题都没有 → Brief 的「Top10 标题共性」算不出来。
    这不是错误，但必须说出来，否则用户不知道数据没导全。"""
    text = "keyword,url,position\nseo 工具,https://a.test/1,1\nseo 工具,https://b.test/2,2\n"
    parsed = parse_serp_csv(text)
    assert parsed.errors == [] and len(parsed.captures) == 1
    assert parsed.warnings and "标题" in parsed.warnings[0]

    with_titles = parse_serp_csv(CSV_OK)
    assert with_titles.warnings == []


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def test_json_object_shape_with_shared_defaults():
    """顶层 market / captured_at 作为默认值，被每组继承 —— Provider 导出
    一次抓取一批词，没必要每词重复写引擎和时间。"""
    text = json.dumps(
        {
            "market": "baidu",
            "captured_at": "2026-10-20T08:00:00+00:00",
            "captures": [
                {
                    "keyword": "seo 工具",
                    "entries": [
                        {"url": "https://a.test/1", "position": 1, "title": "A"},
                        {
                            "url": "https://b.test/2", "position": 2, "title": "B",
                            "snippet": "介绍", "features": ["视频"],
                        },
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    parsed = parse_serp_json(text)
    assert parsed.errors == []
    cap = parsed.captures[0]
    assert (cap.keyword, cap.market) == ("seo 工具", "baidu")
    assert cap.captured_at == datetime(2026, 10, 20, 8, tzinfo=timezone.utc)
    assert [r.position for r in cap.results] == [1, 2]
    assert cap.results[1].features == ["视频"]


def test_json_flat_list_and_single_capture_shape():
    parsed = parse_serp_json(json.dumps(
        [{"keyword": "登山鞋", "results": [{"url": "https://a.test/1", "position": 1}]}]
    ))
    assert parsed.errors == [] and parsed.captures[0].keyword == "登山鞋"

    single = parse_serp_json(json.dumps(
        {"keyword": "登山鞋", "entries": [{"url": "https://a.test/1", "position": 1}]}
    ))
    assert single.captures[0].keyword == "登山鞋"


def test_json_bad_entry_reports_group_and_index():
    text = json.dumps({
        "captures": [{
            "keyword": "seo 工具",
            "entries": [
                {"url": "https://a.test/1", "position": 1},
                {"url": "https://b.test/2", "position": "第一名"},
            ],
        }]
    })
    parsed = parse_serp_json(text)
    assert parsed.skipped == 1
    assert any("第 1 组第 2 条" in e for e in parsed.errors)
    assert len(parsed.captures[0].results) == 1


def test_json_garbage_is_not_silently_empty():
    assert parse_serp_json("不是 JSON").errors
    assert parse_serp_json('{"foo":1}').errors
    assert parse_serp_json("[]").errors


# --------------------------------------------------------------------------
# 站点归属
# --------------------------------------------------------------------------


def test_infer_domain_is_a_hint_not_a_decision():
    """SERP 里竞品域名占多数 —— 这个推断只配用来提示，CLI 仍要求 --site。"""
    caps = [capture_from_fields(keyword="seo 工具", results=[
        result_from_fields(url="https://www.rival.test/a", position=1),
        result_from_fields(url="https://rival.test/b", position=2),
        result_from_fields(url="https://demo.test/c", position=3),
    ])]
    assert infer_domain(caps) == "rival.test"
