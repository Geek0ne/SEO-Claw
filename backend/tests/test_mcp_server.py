"""MCP Server 的工具面。

⚠️ 这里只测「工具面长什么样」，不测协议握手 —— 握手要真起一个
MCP 客户端，那是集成测试的事。**这一层真正要守住的是边界**：
工具集就是权限边界，多一个能写的工具等于把写权限交给提示词。
所以下面有一条**反向**用例：写操作的工具名必须不在列表里。
"""

from __future__ import annotations

import pytest

mcp = pytest.importorskip("mcp", reason="可选依赖，未安装 mcp 时跳过")

from seoclaw.mcp_server import build_server  # noqa: E402


def _tool_names() -> set[str]:
    return set(build_server()._tool_manager._tools)


def test_exposes_the_three_read_only_tools():
    """三个工具，且名字是我们预期的那些。

    ⚠️ 别把清单写死成「必须恰好是这三个」——那会让以后正常加一个只读
    工具都失败。这里断言「该有的都在」，把边界留给下面那条反向用例。
    """
    names = _tool_names()
    assert {"seo_list_sites", "seo_get_report", "seo_audit_url"} <= names


def test_no_write_tools_are_exposed():
    """⚠️ 边界用例：MCP 工具集 = 权限边界。

    工具交给模型自主调用，所以**加一个能写库的工具，等于把写权限交给
    任何能影响提示词的地方**。这条用例让「不小心加了写操作」在测试里
    就红，而不是上线后才发现。
    """
    forbidden = ("delete", "drop", "update", "create", "write", "remove", "truncate")
    for name in _tool_names():
        assert not any(w in name.lower() for w in forbidden), (
            f"暴露了疑似写操作工具：{name}"
        )


def test_tool_instructions_mention_slow_tool():
    """instructions 里必须点明 seo_audit_url 会真的抓网页。

    模型不会自己知道哪个工具贵。不说，它可能为了「查一下」就抓几百页，
    把服务端和目标站一起拖垮。
    """
    server = build_server()
    # ⚠️ 断言的是**这个工具自己的描述里**有没有提醒，不是「所有描述拼起来
    # 有没有出现工具名」。我第一版写成了后者，于是断言工具名出现在描述里
    # ——工具名当然不出现在自己的描述文本中，红的是断言不是代码。
    tool = server._tool_manager._tools["seo_audit_url"]
    desc = tool.description or ""
    assert "慢" in desc or "抓" in desc, (
        f"seo_audit_url 的描述没提醒它会真的抓网页：{desc[:80]}"
    )
