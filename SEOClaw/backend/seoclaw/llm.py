"""LLM 适配层：报告 AI 总结。

## 为什么不引litellm

它 200+ 依赖，会把 `.deps` 撑大一倍，而我们**只需要一个形状**：
OpenAI 兼容的 `POST {base_url}/chat/completions`。OpenRouter / DeepSeek /
自建网关 / vLLM / Ollama 全是这个协议。httpx 已经在了，所以这里 **0 新依赖**。

## 这个模块的硬约束

### 1. 没有凭据必须**明确降级**，不能静默失败

用户配了 ``--llm-summary`` 却因为缺 key 什么都没发生，
他会以为「总结就是这个结论」——**这是最坏的一种失败**：
不是报错，而是给了���个不完整的答案。所以缺配置要抛 ``LLMNotConfigured``，
由 CLI 明确打印「未生成 AI 总结：缺少 X」。

### 2. 总结必须是「重新表述」，不能是「新增结论」

模型拿到的是规则引擎已经算好的确定性事实（分数、分组、排序）。
它的工作是把这些翻译成人话、指出优先级背后的取舍。

⚠️ 如果让它自由发挥，它会**编造**规则没检查过的东西——
「你的服务器响应时间偏慢」这种静态分析根本看不到的说法。
所以 prompt 里显式禁止，并要求它只能引用给定事实。

### 3. 报告正文永远不以模型输出为准

:func:`summarize` 任何情况下返回 ``None`` 表示「没有总结」，
调用方**继续用规则引擎的报告渲染**。AI 总结只是附加段落，
删掉它报告仍然完整——否则模型一挂，整个产品就没报告了。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

# 默认走 OpenRouter：它同时挂着闭源与免费模型，
# 拿来做「验证链路是否通」够用，不必绑死任何一家。
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# ⚠️ 这里要写**裸模型 ID**，不能写配置文件里的完整路径。
# OpenRouter 的 API 用 `stealth/space-bunny-alpha`，
# 写成 `openrouter/stealth/space-bunny-alpha` 会得到
#   HTTP 400 "openrouter/stealth/space-bunny-alpha is not a valid model ID"
# 这个 400 看着像「key 没权限」，极易误判成凭据问题；
# 实际凭据是好的（400 而非 401）。查真实 ID：
#   GET https://openrouter.ai/api/v1/models
#
# ⚠️ 默认值**不是** space-bunny-alpha：实测它在本项目的真实 prompt
# （约 900~1300 字符的事实 JSON）上 13 次全失败，全是
#   502 provider_unavailable / "Provider returned an empty response"，
# 而 40 字的短 prompt 6/6 成功。
# 已排除的解释：缩进/换行（紧凑 JSON 同样失败）、
# max_tokens（900/250/100 三档全 0/3）、长度本身（同长度的散文能过）。
# 结论是这个模型当前扛不住本工具的输入规模，**不能用它做默认值**。
# 想换模型设 SEO_CLAW_LLM_MODEL 即可。
DEFAULT_MODEL = "openrouter/free"

# 凭据按这个顺序找。都不设就抛 LLMNotConfigured。
# ⚠️ SEO_CLAW_* 是当前名字，SEO_AGENT_* 是改名之前的老名字。
# 老名字保留在列表里当后门：直接删掉会让**已有部署静默失效**
# —— 不报错，只是读不到 key，表现为「AI 总结突然全失败」，极难归因。
# 老名字排在后面，新的优先。
_KEY_ENV = (
    "SEO_CLAW_LLM_API_KEY",
    "SEO_AGENT_LLM_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
)


class LLMError(RuntimeError):
    """调用失败。调用方据此决定「降级」还是「报错」。"""


class LLMNotConfigured(LLMError):
    """缺凭据/缺 base_url —— 属于配置问题，不该重试。"""


@dataclass
class LLMConfig:
    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    max_tokens: int = 900
    temperature: float = 0.3

    @classmethod
    def from_env(cls, **kw: Any) -> "LLMConfig":
        key = None
        for name in _KEY_ENV:
            v = os.getenv(name)
            if v:
                key = v
                break
        return cls(
            api_key=key,
            base_url=os.getenv(
            "SEO_CLAW_LLM_BASE_URL"
            or os.getenv("SEO_AGENT_LLM_BASE_URL")
            or DEFAULT_BASE_URL,
        ),
            model=os.getenv(
                "SEO_CLAW_LLM_MODEL"
                or os.getenv("SEO_AGENT_LLM_MODEL")
                or DEFAULT_MODEL,
            ),
            **kw,
        )


SYSTEM_PROMPT = """你在帮站长读懂自己网站的 SEO 体检报告。

严格规则：
1. 只能使用下面「事实」里给出的数据。**禁止推断或补充任何没给的事实**——
   不得提及服务器速度、收录量、排名、外链数量等本次没有检查的维度。
2. 不要重新罗列问题清单，用户已经看得到。你的价值是**指出优先级背后的取舍**：
   哪些先做收益最大、哪些可以先放着、哪些可能是误报不用管。
3. 用中文，具体、不空泛。禁止「建议您持续优化 SEO」这类无信息量的话。
4. 不超过 5 句话。
"""


def _build_prompt(report: Any, max_issues: int = 12) -> str:
    """把报告压成给模型的事实清单。

    ⚠️ 只喂**确定性事实**：分数、分组计数、排序后的前若干条问题。
    不喂全文——一是 token，二是全文里的描述文字容易让模型跟着
    复述而失去「重新表述」的余地。
    """
    counts: dict[str, int] = {}
    for s in ("critical", "high", "medium", "low", "info"):
        counts[s] = 0
    for i in report.issues:
        key = getattr(i.severity, "value", str(i.severity))
        counts[key] = counts.get(key, 0) + 1

    facts: dict[str, Any] = {
        "站点": report.domain,
        "抓取页数": report.pages_crawled,
        "发现 URL 数": report.pages_discovered,
        "问题总数": len(report.issues),
        "按严重度": counts,
    }
    if report.health_score is not None:
        facts["健康分"] = round(float(report.health_score), 1)
        dims = (report.score_breakdown or {}).get("dimension_scores") or {}
        if dims:
            facts["维度分"] = {k: round(float(v), 1) for k, v in dims.items()}
    else:
        facts["健康分"] = None
        facts["重要"] = "本次没有审到任何页面，不要给出任何结论性判断"

    top = []
    for i in report.issues[:max_issues]:
        top.append(
            {
                "标题": i.title,
                "严重度": getattr(i.severity, "value", str(i.severity)),
                "影响页数": len(i.evidence.get("affected_urls", []) or [])
                or len(i.evidence.get("example_urls", []) or []),
            }
        )
    facts["问题（按优先级，最多 %d 条）" % max_issues] = top
    return json.dumps(facts, ensure_ascii=False, indent=2)


def _extract_text(payload: dict[str, Any]) -> str:
    """从 OpenAI 兼容响应里取正文。

    ⚠️ 有些网关（OpenRouter 免费路由、部分自建）会返回
    ``choices: []`` —— 上游没路由到任何模型。这不是我们的 bug，
    但必须报错而不是返回空串：空串会被调用方当成「总结是空的」，
    用户看到一份没有总结的报告却不知道为什么。
    """
    choices = payload.get("choices") or []
    if not choices:
        raise LLMError(f"上游没有返回候选（choices 为空）：{json.dumps(payload)[:200]}")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):  # 部分网关返回 content 块数组
        content = "".join(
            c.get("text", "") for c in content if isinstance(c, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise LLMError("上游返回了空内容")
    return content.strip()


def chat(
    prompt: str,
    *,
    system: str = SYSTEM_PROMPT,
    config: Optional[LLMConfig] = None,
    client: Optional[httpx.Client] = None,
) -> str:
    """调一次 OpenAI 兼容 chat/completions，返回正文。

    ``client`` 参数只为测试注入 MockTransport；生产走默认 client。
    """
    cfg = config or LLMConfig.from_env()
    if not cfg.api_key:
        raise LLMNotConfigured(
            "未配置 LLM 凭据（环境变量任选其一："
            + " / ".join(_KEY_ENV)
            + "）。报告仍可正常生成，只是没有 AI 总结。"
        )

    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
    }
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }

    owns = client is None
    http = client or httpx.Client(timeout=cfg.timeout)
    try:
        resp = http.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"调用 LLM 失败：{type(exc).__name__}: {exc}") from exc
    finally:
        if owns:
            http.close()

    if resp.status_code >= 400:
        # ⚠️ 401/403 要单独说清是「凭据不对」，不是「服务不可用」——
        # 这两种的处置完全不同（前者去改 key，后者该重试/换模型）。
        hint = ""
        if resp.status_code in (401, 403):
            hint = "（凭据无效或无权限，建议检查 API key）"
        raise LLMError(f"LLM 返回 HTTP {resp.status_code}{hint}：{resp.text[:200]}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise LLMError(f"LLM 返回的不是 JSON：{resp.text[:200]}") from exc
    return _extract_text(payload)


def summarize(
    report: Any,
    *,
    config: Optional[LLMConfig] = None,
    client: Optional[httpx.Client] = None,
    max_issues: int = 12,
) -> Optional[str]:
    """生成报告 AI 总结。任何失败都返回 ``None``，**不抛异常**。

    ⚠️ 刻意吞掉所有异常：AI 总结是锦上添花，调用方已经有完整的
    规则引擎报告。总结失败绝不能让报告整个消失——那等于把一个
    可选功能变成单点故障。

    要区分「没生成」的原因（给用户提示用），调 :func:`chat` 即可。
    """
    try:
        return chat(_build_prompt(report, max_issues), config=config, client=client)
    except LLMError:
        return None
    except Exception:  # noqa: BLE001 — 见上：这个模块绝不能让报告挂掉
        return None