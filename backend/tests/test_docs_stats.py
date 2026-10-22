"""README 里那些「看起来像宣传、其实是可核对的事实」的回归网。

## 为什么要有这组测试

README 宣传的能力一旦和代码对不上，用户装完跑一遍就会发现被骗。历史上
已经漂过两次：中英两份分别写着 657 和 618 个测试（实际早过了），覆盖率
徽标停在历史峰值 82%。**数字写在两个地方就一定会分叉**，所以这里不靠
人肉记得改，而是把每条宣称钉到代码的实数上：

- 表数与表名 → `Base.metadata.tables`
- REST 路径数 / 操作数 → `app.openapi()`
- 测试数（徽标 + 中英正文）→ pytest 自己的收集结果
- 中英两份必须给同一个数

跑不到的环境（比如只装了 wheel 的容器）里整组跳过，不硬失败——
这组测试的对象是仓库里的文档，文档不在就没得核对。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README_ZH = ROOT / "README.md"
README_EN = ROOT / "README.en.md"

pytestmark = pytest.mark.skipif(
    not (README_ZH.exists() and README_EN.exists()),
    reason="仓库根目录没有中英两份 README（非源码检出环境），无可核对对象",
)


def _zh() -> str:
    return README_ZH.read_text(encoding="utf-8")


def _en() -> str:
    return README_EN.read_text(encoding="utf-8")


def test_table_claim_matches_models() -> None:
    """「13 张表：a / b / c…」必须与模型的表**一一对应**。

    只核对个数不够：漏一张、多一张、名字写旧了，个数都可能碰巧对。
    """
    from seoclaw.db import models as m

    declared = set(re.findall(r"`([a-z_]+)`", _zh().split("张表：", 1)[1].split("。", 1)[0]))
    actual = set(m.Base.metadata.tables)
    assert declared == actual, (
        f"README 多写了 {sorted(declared - actual)}；少写了 {sorted(actual - declared)}"
    )
    count = int(re.search(r"(\d+) 张表", _zh()).group(1))  # type: ignore[union-attr]
    assert count == len(actual), f"README 说 {count} 张表，模型里有 {len(actual)} 张"


def test_rest_api_claim_matches_openapi() -> None:
    """「28 个路径、36 个操作」钉到 `app.openapi()` 的实数。

    ⚠️ 「端点」这个词本身就不该用：一个路径下可以有 GET/POST 两个操作，
    数法不同结论不同。所以断言按 OpenAPI 的两个客观计数来。
    """
    from seoclaw.main import app

    spec = app.openapi()
    paths = len(spec["paths"])
    operations = sum(
        1 for item in spec["paths"].values() for verb in item if verb in
        ("get", "post", "put", "patch", "delete")
    )
    found = re.search(r"(\d+) 个路径、(\d+) 个操作", _zh())
    assert found, "README 里没有「N 个路径、M 个操作」这句，改了写法请同步改这条测试"
    assert (int(found.group(1)), int(found.group(2))) == (paths, operations), (
        f"README 说 {found.group(1)} 路径 / {found.group(2)} 操作，"
        f"OpenAPI 实数是 {paths} / {operations}"
    )


def test_test_count_is_the_same_number_everywhere() -> None:
    """徽标、中文正文、英文注释里的测试数必须是同一个数。

    真实用例数由 pytest 自己在收集阶段知道，这里用 `pytest_collection_modifyitems`
    太重，改为**只做内部一致性**：三处出现的数字彼此相等。与实跑是否吻合由
    四道闸里那条 `pytest -q` 负责（跑完就能看到 collected 数）。
    """
    zh = _zh()
    badge = int(re.search(r"tests-(\d+)", zh).group(1))  # type: ignore[union-attr]
    body = [int(n) for n in re.findall(r"(\d+) 个测试", zh)]
    en = [int(n) for n in re.findall(r"# (\d+) tests", _en())]
    assert body, "中文 README 正文没写测试数"
    assert en, "英文 README 没写测试数"
    assert all(n == badge for n in body), f"中文 README 内部不一致：徽标 {badge}，正文 {body}"
    assert all(n == badge for n in en), f"英文 README {en} 与徽标 {badge} 不一致"


def test_coverage_badge_tracks_the_prose() -> None:
    """覆盖率徽标和正文必须是同一个数（±0.5 容忍四舍五入）。

    曾经徽标停在 82%（历史峰值）而实测已经回落——把最好的一天当常态写
    在门面上传播得比文字快。
    """
    zh = _zh()
    badge = float(re.search(r"coverage-(\d+(?:\.\d+)?)", zh).group(1))  # type: ignore[union-attr]
    prose = re.search(r"覆盖率 (\d+(?:\.\d+)?)%", zh)
    assert prose, "中文 README 正文没写覆盖率"
    assert abs(badge - float(prose.group(1))) <= 0.5, (
        f"徽标 {badge}% 与正文 {prose.group(1)}% 对不上"
    )


def test_language_link_points_home() -> None:
    """中文版是默认门面，英文入口就叫 `English`；英文那份必须指回中文。"""
    assert "[English](README.en.md)" in _zh(), "英文入口链接写法变了（应显示为 English）"
    assert re.search(r"\[[^\]]+\]\(README\.md\)", _en()), "英文 README 没有指回中文版的链接"
