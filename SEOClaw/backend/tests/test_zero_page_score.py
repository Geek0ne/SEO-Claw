# -*- coding: utf-8 -*-
"""0 页时不给分：健康分不能是 100。

## 为什么单独一个文件

这是今晚第 N 次同一个病：**把「没审到」当成了「审过且没问题」**。
之前修过三个同类，只是方向不同：

- gymshark：子域问题算进主站分 → 0.0 分（算多了）
- `_content_same`：两页都退化成登录页 → 判「内容相同」（没看到就下了结论）
- sitemap 递归：只对成功的子文件计数 → 失败请求漏过闸门（没数到的当没有）
- **本文件**：`max(total_pages, 1)` 把 0 页兜底成 1 页 → 无问题 → **满分 100**

前三个我都补了测试，这个也补。但更重要的是：**每一条都是先实跑撞上，
才补的测试**。所以下面每个用例都写了它对应的那次真实事故，
而不是「函数应该返回什么」。

## 判据

「没审到」和「没问题」是两件事，报成 100 分就是把前者说成后者。
用户看到「健康分 100.0、零问题」会以为全站审过了，然后放心不管了——
而实际上一页都没抓到。lobste.rs 的 robots.txt 是
`User-agent: * / Disallow: /`（全站禁抓），守规矩的结果就是 0 页。
"""
from seoclaw.models import Issue, Severity
from seoclaw.report import render_markdown, summarize_console
from seoclaw.scoring import score


def _mk(code: str, url: str = "https://example.com/") -> Issue:
    return Issue(code=code, severity=Severity.MEDIUM, url=url, title=code, description=code)


class TestZeroPageNoScore:
    """0 页 → 不给分。"""

    def test_zero_pages_returns_none_not_100(self):
        """核心：0 页必须给 None，给 100 就是撒谎。"""
        health, bd = score([], 0)
        assert health is None, f"0 页却给了 {health} 分——没审到不能说没问题"
        assert bd["not_evaluated"] is True
        assert bd["reason"] == "no_pages_audited"

    def test_zero_pages_with_issues_also_none(self):
        """0 页但 issues 非空时同样不给分。

        这种组合理论上不该出现（没页面就没规则输入），但万一出现了，
        也不能拿那几条问题去算分——分母是 0，算出来的比例毫无意义。
        """
        health, _bd = score([_mk("title.missing")], 0)
        assert health is None

    def test_negative_pages_returns_none(self):
        """负数是脏数据，但同样不能变成满分。"""
        health, _bd = score([], -1)
        assert health is None

    def test_one_page_still_scores_normally(self):
        """1 页是合法样本，必须照常给分——别把兜底去得太狠。

        兜底 max(total_pages, 1) 本意是防除零，不是防「样本小」。
        修 0 页不能顺手把 1 页也打成未评估。
        """
        health, bd = score([], 1)
        assert health == 100.0
        assert bd.get("not_evaluated") is None

    def test_issue_on_single_page_still_deducts(self):
        """1 页有 1 个问题 → 应该扣分，不能因为「页数少」就跳过计分。"""
        health, bd = score([_mk("title.missing")], 1)
        assert health is not None
        assert health < 100.0, "1 页 1 问题却满分，扣分逻辑被绕过了"
        assert bd["per_code"]["title.missing"]["affected_pages"] == 1