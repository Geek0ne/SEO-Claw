"""站点归属验证：这个站凭什么算你的。

## 两条通道

| 方式 | 用户做什么 | 适合 |
|---|---|---|
| **DNS TXT** | 在 `_seo-claw.你的域名` 加一条 TXT | 有 DNS 权限的人 |
| **HTML meta** | 首页 `<head>` 加一个 meta 标签 | WordPress 用户装插件即可 |

## ⚠️ 未验证的站点能扫，但不能进监控

这是产品规则不是技术限制：告警要**持续抓取**，而抓别人的站来给自己
报警，等于提供了一个免费爬虫跳板。所以 `monitoring_enabled` 只对已验证
站点开放。

## ⚠️ DNS 校验失败 ≠ 站点不归你

解析器超时、被限流、DNS 记录刚生效未传播，都会返回「查不到」。所以
返回值必须区分 **no / yes / unknown** 三态，把 unknown 明确告诉用户
「我暂时查不到，手动确认一下」，而不是一口咬定「验证失败」。
"""

from __future__ import annotations

import re
import secrets
import subprocess
from dataclasses import dataclass
from typing import Literal

import httpx

DNS_PREFIX = "_seo-claw"
META_NAME = "seo-claw-verification"

Verdict = Literal["yes", "no", "unknown"]


def new_token() -> str:
    return "sc-" + secrets.token_urlsafe(24)


def dns_instructions(domain: str, token: str) -> str:
    return (
        f"在 {domain} 的 DNS 里加一条 TXT 记录：\n"
        f"  主机名：{DNS_PREFIX}\n"
        f"  值：{token}\n"
        f"或等效写法：{DNS_PREFIX}.{domain}  TXT  \"{token}\""
    )


def meta_instructions(token: str) -> str:
    return (
        "在首页 <head> 里加：\n"
        f'  <meta name="{META_NAME}" content="{token}">'
    )


@dataclass(frozen=True, slots=True)
class CheckResult:
    verdict: Verdict
    detail: str


def check_dns(domain: str, token: str, *, timeout: float = 6.0) -> CheckResult:
    """查 DNS TXT。⚠️ 查不到时返回 unknown，不返回 no —— 见模块说明。"""
    name = f"{DNS_PREFIX}.{domain}"
    try:
        p = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=1", "TXT", name],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return CheckResult("unknown", "本机没有 dig 命令，无法自动查 DNS。请手动确认记录已添加。")
    except subprocess.TimeoutExpired:
        return CheckResult("unknown", "查 DNS 超时。可能是网络受限或解析器无响应，请手动确认。")

    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return CheckResult("unknown", f"dig 返回非零退出码：{(p.stderr or '').strip()[:120]}")
    if not out:
        return CheckResult("no", f"没有查到 {name} 的 TXT 记录。记录可能还没生效，或加错了主机名。")
    if token in out:
        return CheckResult("yes", f"DNS TXT 已匹配（{name}）。")
    return CheckResult("no", f"{name} 有 TXT 记录，但内容与本次 token 不一致。若你重新生成过 token，请用最新的。")


_META_RE = re.compile(
    r"""<meta[^>]+name=["']%s["'][^>]*content=["']([^"']+)["']""" % META_NAME,
    re.I,
)
_META_RE_ALT = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]*name=["']%s["']""" % META_NAME,
    re.I,
)


def check_meta(domain: str, token: str, *, timeout: float = 12.0) -> CheckResult:
    """抓首页找 meta 标签。⚠️ 同上，抓不到不等于不存在。

    ⚠️ 2026-10-25 修复：domain 来自用户建站输入，抓取前必须过
    ``web.guard``（与 quick-scan 同一道闸）——否则提交
    ``169.254.169.254`` 这类目标就成了 SSRF：借验证接口打云元数据 /
    内网。解析失败按模块口径归 ``unknown``（查不到 ≠ 不存在）；
    命中保留网段 / 黑名单归 ``no``（明确拒绝，不是查不到）。
    重定向后的跳转目标不再复检，属 guard.py 已声明的残余风险，
    真正的护栏是网络层。
    """
    from ..web.guard import BlockedTarget, check_denied, resolve_and_check

    url = f"https://{domain}/"
    try:
        check_denied(domain)
        resolve_and_check(url)
    except BlockedTarget as exc:
        reason = str(exc)
        if reason.startswith("域名解析失败"):
            return CheckResult("unknown", f"{reason}。请手动确认首页是否含该标签。")
        return CheckResult(
            "no", f"目标被安全策略拒绝（{reason}）。归属验证不能指向内网或保留地址。"
        )
    try:
        # 与 crawler.py 同款 Client 用法：抓取行为本身走连接池。
        # 目标合法性已由上方 guard 校验（协议 / 黑名单 / 解析 IP）。
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "SEO-Claw-Verification/1.0"}) as client:
            r = client.get(url)
    except Exception as exc:  # noqa: BLE001
        return CheckResult("unknown", f"访问 {url} 失败：{type(exc).__name__}。请手动确认首页是否含该标签。")

    if r.status_code >= 400:
        return CheckResult("unknown", f"{url} 返回 {r.status_code}，读不到首页 HTML。请手动确认。")

    html = r.text
    m = _META_RE.search(html) or _META_RE_ALT.search(html)
    if not m:
        return CheckResult("no", f"首页没找到 <meta name=\"{META_NAME}\"> 标签。")
    if m.group(1).strip() == token:
        return CheckResult("yes", "首页 meta 标签已匹配。")
    return CheckResult("no", "首页有该 meta 标签，但内容与本次 token 不一致。若你重新生成过 token，请用最新的。")
