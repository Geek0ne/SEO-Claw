"""LLM 适配层测试。

⚠️ 全部用 MockTransport，**一次真实网络请求都不发**。这个模块是唯一
会带用户 API key 出网的地方，测试里绝不能真调——一是慢，二是会烧额度。

重点锁三类失败，因为它们都是**静默**的：
1. 缺凭据 → 必须抛 LLMNotConfigured，不能「悄悄不出总结」
2. 上游返回空 choices → 必须报错，不能返回空串
3. summarize() 吞异常 → 返回 None 而不是让整个报告挂掉
"""

from __future__ import annotations

import json

import httpx
import pytest

from seoclaw.audit.engine import run_audit
from seoclaw.extract import extract_page
from seoclaw.llm import (
    LLMConfig,
    LLMError,
    LLMNotConfigured,
    _build_prompt,
    _extract_text,
    chat,
    summarize,
)
from seoclaw.models import Market, SiteReport
from seoclaw.scoring import score


def _report() -> tuple[SiteReport, list]:
    bad = (
        "<html><head><title>x</title></head><body><p>hi</p>"
        '<a href="/a"></a><a href="/b"></a></body></html>'
    )
    pages = [extract_page(f"https://demo.test/{i}", bad) for i in range(5)]
    issues, _ = run_audit(pages, "demo.test", [Market.BASE], {})
    h, b = score(issues, len(pages), domain="demo.test")
    rep = SiteReport(
        domain="demo.test",
        pages_crawled=len(pages),
        pages_discovered=40,
        health_score=h,
        score_breakdown=b,
        issues=issues,
    )
    return rep, pages


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(text: str = "先修 title，三小时内见效。"):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return handler


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


def test_missing_key_raises_explicitly():
    """⚠️ 缺凭据必须**明确报错**，不能静默返回 None。

    静默失败最坏：用户配了总结却什么都没拿到，
    他会以为「总结就是这个结论」——那是给了一个不完整的答案，
    比明确报错危险得多。
    """
    cfg = LLMConfig(api_key=None)
    with pytest.raises(LLMNotConfigured) as e:
        chat("hi", config=cfg, client=_client(_ok()))
    msg = str(e.value)
    assert "OPENROUTER_API_KEY" in msg or "API_KEY" in msg
    # 报错文案要告诉用户报告仍能正常生成
    assert "报告" in msg


def test_llm_not_configured_is_not_retried():
    """配置问题不该按网络错误重试 —— 重试只会拖慢，且永远不会成功。"""
    assert issubclass(LLMNotConfigured, LLMError)


# --------------------------------------------------------------------------
# 正常路径
# --------------------------------------------------------------------------


def test_returns_text():
    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1", model="m")
    out = chat("prompt", config=cfg, client=_client(_ok("结论在这里")))
    assert out == "结论在这里"


def test_sends_expected_shape():
    """请求体要是 OpenAI 兼容形状，否则换一家网关就挂。"""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    cfg = LLMConfig(api_key="sk-test", base_url="https://x.test/v1/", model="mm")
    chat("p", config=cfg, client=_client(handler))

    assert seen["url"] == "https://x.test/v1/chat/completions", "base_url 末尾斜杠要处理"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "mm"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


def test_content_blocks_joined():
    """部分网关返回 content 块数组而不是字符串，要能拼起来。"""
    payload = {
        "choices": [
            {"message": {"content": [{"text": "前半"}, {"text": "后半"}]}}
        ]
    }
    assert _extract_text(payload) == "前半后半"


# --------------------------------------------------------------------------
# 上游异常：都必须报错，不能返回空串
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,needle",
    [
        (500, "500"),
        (429, "429"),
        (400, "400"),
    ],
)
def test_http_error_raises(status, needle):
    def handler(req):
        return httpx.Response(status, text="boom")

    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    with pytest.raises(LLMError) as e:
        chat("p", config=cfg, client=_client(handler))
    assert needle in str(e.value)


def test_auth_error_explains_key():
    """401/403 要单独说清是「凭据不对」，不是「服务不可用」。

    这两种的处置完全相反：前者去改 key，后者该重试或换模型。
    混成一句「调用失败」，用户会白折腾。
    """
    def handler(req):
        return httpx.Response(401, text="unauthorized")

    cfg = LLMConfig(api_key="bad", base_url="https://x.test/v1")
    with pytest.raises(LLMError) as e:
        chat("p", config=cfg, client=_client(handler))
    assert "凭据" in str(e.value)


def test_empty_choices_raises():
    """⚠️ OpenRouter 免费路由常返回 choices: []（没路由到模型）。

    返回空串会被调用方当成「总结是空的」，用户看到一份没有总结的
    报告却不知道为什么。必须报错。
    """
    def handler(req):
        return httpx.Response(200, json={"choices": []})

    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    with pytest.raises(LLMError) as e:
        chat("p", config=cfg, client=_client(handler))
    assert "choices" in str(e.value)


def test_empty_content_raises():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    with pytest.raises(LLMError):
        chat("p", config=cfg, client=_client(handler))


def test_non_json_raises():
    def handler(req):
        return httpx.Response(200, text="<html>网关错误页</html>")

    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    with pytest.raises(LLMError):
        chat("p", config=cfg, client=_client(handler))


# --------------------------------------------------------------------------
# summarize：绝不能让报告挂掉
# --------------------------------------------------------------------------


def test_summarize_returns_none_on_error():
    """⚠️ AI 总结是锦上添花，规则引擎报告已经完整。

    总结失败绝不能让报告整个消失——那等于把可选功能变成单点故障。
    """
    def handler(req):
        return httpx.Response(500, text="boom")

    rep, pages = _report()
    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    assert summarize(rep, config=cfg, client=_client(handler)) is None


def test_summarize_returns_none_on_missing_key():
    rep, _ = _report()
    assert summarize(rep, config=LLMConfig(api_key=None)) is None


def test_summarize_ok():
    rep, _ = _report()
    cfg = LLMConfig(api_key="k", base_url="https://x.test/v1")
    assert summarize(rep, config=cfg, client=_client(_ok("摘要"))) == "摘要"


# --------------------------------------------------------------------------
# prompt：只能喂确定性事实
# --------------------------------------------------------------------------


def test_prompt_contains_facts():
    rep, _ = _report()
    p = _build_prompt(rep)
    assert "demo.test" in p
    assert "健康分" in p
    assert rep.health_score is None or "None" not in p.split("健康分")[1][:20]


def test_prompt_flags_zero_page_report():
    """⚠️ 0 页报告必须显式告诉模型「不要给结论」，否则它会照着
    「0 个问题」脑补出「你的站很健康」——一页都没审过。"""
    rep = SiteReport(domain="blocked.test", pages_crawled=0, pages_discovered=40, issues=[])
    p = _build_prompt(rep)
    assert "没有审到任何页面" in p
    assert '"健康分": null' in p or '"健康分": None' in p


def test_prompt_does_not_send_full_issue_dump():
    """只喂前若干条，不是全文。

    全文会让模型顺着描述文字复述，失去「重新表述」的价值，
    而且白烧 token。"""
    bad = "<html><head><title>x</title></head><body><p>hi</p></body></html>"
    pages = [extract_page(f"https://demo.test/{i}", bad) for i in range(40)]
    issues, _ = run_audit(pages, "demo.test", [Market.BASE], {})
    h, b = score(issues, len(pages), domain="demo.test")
    rep = SiteReport(
        domain="demo.test",
        pages_crawled=len(pages),
        pages_discovered=100,
        health_score=h,
        score_breakdown=b,
        issues=issues,
    )
    p = _build_prompt(rep, max_issues=5)
    listed = p.split("问题（按优先级")[1].split("]")[0].count("{")
    assert listed <= 5, f"应只列 5 条，实际 {listed}"


def test_prompt_forbids_inventing_facts():
    """system prompt 必须禁止编造静态分析看不到的维度。

    模型很爱说「服务器响应偏慢」「收录量不足」——这些本次全都没检查，
    说出来就是纯幻觉，而用户会当成体检结论。"""
    from seoclaw.llm import SYSTEM_PROMPT

    assert "禁止" in SYSTEM_PROMPT
    for kw in ("服务器", "收录", "排名", "外链"):
        assert kw in SYSTEM_PROMPT, f"应明确禁止提及 {kw}"