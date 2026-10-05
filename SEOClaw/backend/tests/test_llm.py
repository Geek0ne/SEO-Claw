"""AI 总结链路。

⚠️ 这些用例的存在理由：`llm.chat()` 声明了 ``client`` 参数「只为测试注入
MockTransport」，但**在那之前没有任何一个测试真的走过它** —— 也就是说
这条链路从来没被端到端验证过，只在真实环境配了 key 才第一次跑。
那正是「写完了 ≠ 交付了」。

所以这里全部离线：不给 key、不发真实请求。
"""

from __future__ import annotations

import httpx
import pytest

from seoclaw.llm import LLMConfig, LLMNotConfigured, chat, summarize


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _cfg() -> LLMConfig:
    return LLMConfig(api_key="test-key", base_url="https://llm.invalid/v1", model="m")


def test_chat_returns_text():
    def handler(req: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, json={
            "choices": [{"message": {"content": "先修标题。"}}]})
        return body

    assert chat("问题清单", config=_cfg(), client=_client(handler)) == "先修标题。"


def test_chat_sends_expected_request_shape():
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        seen["url"] = str(req.url)
        seen["body"] = _j.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    chat("hi", config=_cfg(), client=_client(handler))
    assert seen["url"].endswith("/chat/completions"), seen["url"]
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "m"
    assert seen["body"]["max_tokens"] > 0
    assert "temperature" in seen["body"]


def test_chat_without_key_raises_not_configured(monkeypatch):
    for name in ("SEO_CLAW_LLM_API_KEY", "OPENAI_API_KEY",
                 "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LLMNotConfigured):
        chat("hi", config=LLMConfig(api_key=None))


def test_chat_raises_on_http_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(Exception):
        chat("hi", config=_cfg(), client=_client(handler))


def test_chat_raises_on_malformed_payload():
    """⚠️ 模型返回结构不对时必须**炸**，不能返回 None。
    返回 None 会让上层显示成「AI 没说话」，而真相是「格式变了」。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(Exception):
        chat("hi", config=_cfg(), client=_client(handler))


def test_summarize_swallows_errors():
    """总结失败绝不能让报告整个消失 —— 这是它被设计成返回 None 的理由。"""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert summarize(object(), config=_cfg(), client=_client(handler)) is None


def test_summarize_builds_prompt_from_report():
    """⚠️ 必须只喂**确定性事实**：分数、分组计数、排序后的问题。

    不喂全文的原因是：token 贵，且全文里的描述文字容易让模型跟着复述，
    失去「重新表述」的余地。
    """
    import json as _j
    from seoclaw.models import Issue, Severity, SiteReport

    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["prompt"] = _j.loads(req.content)["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    rep = SiteReport(
        domain="example.com", pages_crawled=12, pages_discovered=40,
        health_score=72.5,
        issues=[Issue(code="title.missing", severity=Severity.HIGH,
                      title="页面没有标题", evidence={})],
    )
    assert summarize(rep, config=_cfg(), client=_client(handler)) == "ok"
    assert "example.com" in seen["prompt"]
    assert "72.5" in seen["prompt"]
    # ⚠️ 刻意**不**断言 code 出现在 prompt 里：_build_prompt 只喂
    # 标题/严重度/影响页数。系统提示明写「不要重新罗列问题清单」——
    # 喂规则 code 会让模型照着规则名复述，失去重新表述的余地。
    assert "页面没有标题" in seen["prompt"]
    assert "high" in seen["prompt"]


def test_prompt_refuses_to_conclude_when_no_pages():
    """⚠️ 一页都没审到时，提示必须让模型**不要下任何结论**。
    否则用户会收到一份基于零证据的「你的网站很健康」。"""
    import json as _j
    from seoclaw.models import SiteReport

    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["prompt"] = _j.loads(req.content)["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    summarize(SiteReport(domain="e.com", pages_crawled=0, pages_discovered=0,
                         issues=[]), config=_cfg(), client=_client(handler))
    assert "不要给出任何结论" in seen["prompt"]
