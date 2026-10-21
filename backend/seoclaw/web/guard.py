"""公网部署的守卫：SSRF 拦截 + 限流。

## 为什么必须有这个模块

Web 端的功能本质是**「用户给个网址，服务端去访问它」**。放到公网上，
这就等于把一台服务器的出网能力交给任何陌生人。没有这两道闸，
开放服务当天就会出事：

- **SSRF**：用户填 `http://169.254.169.254/latest/meta-data/iam/...`，
  云平台把该容器的 IAM 凭据原文返回。拿到就能横向拿整个项目的数据、
  以你的身份调 API。**Render / AWS / GCP / 阿里云全都有这个地址。**
- **限流**：不限流的话，别人写个 for 循环就能把你的 IP 当爬虫用。
  被目标站按 IP 拉黑，**你整台机器的 IP 都废了**——不只这个服务。

## SSRF 的残余风险（说清楚，别假装堵死了）

这里做的是「**提交时解析 DNS 并核对 IP**」。它挡得住用户直接填内网地址，
但挡不住这两类：

1. **DNS rebinding**：第一次解析返回公网 IP 通过校验，第二次
   （真正建连时）返回 127.0.0.1。
2. **重定向**：外站 302 跳到 `http://169.254.169.254/`。httpx 的
   ``follow_redirects=True`` 会照跟。

彻底堵住需要「在 socket 层做 connect-time 校验」，也就是自己实现
``httpx`` 的 transport 钩子。当前版本**不做**——那是改架构的事，
而且即便做了也得配 egress 网络策略双保险。**真正的护栏是网络层**：
Render 上把出网限制到必要目的地，或者干脆给个 egress allowlist。

所以这一层是**减少攻击面，不是消除**。真上公网必须同时上网络策略。
"""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


class BlockedTarget(Exception):
    """目标被安全策略拒绝。消息可以直接回给用户。"""


# --------------------------------------------------------------------------
# SSRF
# --------------------------------------------------------------------------

_ALLOWED_SCHEMES = ("http", "https")

# 云厂商的实例元数据服务。**即使 DNS 层面拦住了内网，这些也必须硬编码**：
# 它们可能通过非标准 Host 头被访问，绕过基于 IP 的判断。
_BLOCKED_HOSTS = frozenset({
    "169.254.169.254",          # AWS / GCP / Azure / 阿里云 / DigitalOcean
    "metadata.google.internal", # GCP 旧写法
    "metadata.goog",            # GCP
    "100.100.100.200",          # 阿里云
})

_BLOCKED_PORTS = frozenset({
    22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211,
    27017, 27018, 11212, 2375, 2376, 9000,
})


def _is_forbidden_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> Optional[str]:
    # ⚠️ 注解不用 ipaddress._BaseAddress：那是私有名字（下划线开头），
    # 类型标注跟着运行时内部实现走，换个 Python 版本就崩注解。
    """内网/保留地址一律拒绝。返回拒绝原因，全局则返回 None。"""
    if ip.is_loopback:
        return "回环地址"
    if ip.is_private:
        return "私有网段"
    if ip.is_link_local:
        # 含 169.254.0.0/16 —— 云元数据就在这里
        return "链路本地地址"
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return "保留地址"
    if getattr(ip, "is_site_local", False):
        return "站点本地地址"
    # IPv4-mapped IPv6（::ffff:127.0.0.1）—— is_loopback 对部分版本不生效
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _is_forbidden_ip(mapped)
    return None


def resolve_and_check(url: str, *, timeout: float = 3.0) -> str:
    """校验目标 URL 可否访问。返回规范化后的 URL。

    校验顺序是「便宜的先做」：协议 → 端口 → 字面 IP → DNS 解析。
    这样绝大多数请求不会触发 DNS 查询（DNS 是这条路径上最慢的一步，
    而且它本身也是攻击面——可被用来打作者的 DNS 服务器）。
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise BlockedTarget(
            f"只支持 http/https，收到 {parsed.scheme or '（没有协议）'}"
        )

    host = parsed.hostname
    if not host:
        raise BlockedTarget("看不出主机名")

    if host in _BLOCKED_HOSTS:
        raise BlockedTarget("目标是云平台内部地址，拒绝")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise BlockedTarget("端口号不合法") from None
    if port in _BLOCKED_PORTS:
        raise BlockedTarget(f"端口 {port} 不对公众开放")

    # 字面 IP：不用查 DNS，直接判
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        reason = _is_forbidden_ip(ip)
        if reason:
            raise BlockedTarget(f"目标是{reason}，拒绝")
        return url

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedTarget(f"域名解析失败：{exc.strerror or exc}") from None

    if not infos:
        raise BlockedTarget("域名解析不出地址")

    # ⚠️ 必须核对**全部**解析结果，不是第一个。
    # 一个域名完全可以同时返回公网 A 记录和 127.0.0.1，
    # 只查第一个等于把这个洞留着。任一条命中就整体拒绝。
    for info in infos:
        addr = str(info[4][0])  # getaddrinfo 的 stub 里这里是 str | int
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])  # 去掉 IPv6 zone id
        except ValueError:
            raise BlockedTarget(f"解析出无法识别的地址：{addr}") from None
        reason = _is_forbidden_ip(ip)
        if reason:
            raise BlockedTarget(
                f"{host} 解析到{reason}（{addr}），拒绝。"
                "这是典型的 DNS rebinding 特征。"
            )
    return url


# --------------------------------------------------------------------------
# 限流
# --------------------------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class RateLimiter:
    """按 IP 的令牌桶。

    为什么必须自己做而不引 slowapi：整个项目零 Web 框架依赖之外的运行时
    依赖是既定原则（``pip install seoclaw`` 只装爬站必需的 8 个包）。
    令牌桶本身三十行能写对，引一个包不值得。
    """

    rate: float = 0.2        # 每秒补几个令牌
    burst: float = 3.0       # 桶容量 = 突发额度
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _max_keys: int = 10_000  # 防内存被伪造 IP 撑爆

    def allow(self, key: str) -> tuple[bool, float]:
        """返回 ``(是否放行, 建议等待秒数)``。"""
        now = time.monotonic()

        if key not in self._buckets and len(self._buckets) >= self._max_keys:
            # 满了就清最旧的一半。攻击者可以靠伪造 IP 逼我们清空，
            # 那就让他的记录一起没了——这是可接受的降级，
            # 更好的做法是在 nginx 层就按 IP 限流。
            cutoff = now - 300
            stale = [k for k, b in self._buckets.items() if b.updated < cutoff]
            for k in stale:
                del self._buckets[k]
            if len(self._buckets) >= self._max_keys:
                oldest = sorted(self._buckets, key=lambda k: self._buckets[k].updated)
                for k in oldest[: len(oldest) // 2]:
                    del self._buckets[k]

        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = _Bucket(tokens=self.burst - 1, updated=now)
            return True, 0.0

        elapsed = max(0.0, now - bucket.updated)
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
        bucket.updated = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0

        return False, (1.0 - bucket.tokens) / self.rate


def client_ip(request) -> str:
    """从请求里取客户端 IP。

    ⚠️ **X-Forwarded-For 只有在你确知前面只有一个可信代理时才能信。**
    Render 在前面放了它自己的代理，但任何人都能自己发一个
    ``X-Forwarded-For: 1.2.3.4``——若我们直接取第一个值，限流就成了摆设
    （攻击者每次换个假 IP 即可）。

    这里取**最右侧**一跳，并把它当成「可信代理告诉我们的连接来源」。
    前面还有 CDN 时这个值是 CDN 的 IP，限流会变粗——宁可粗不可废。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    # ⚠️ getattr 两层：`request.client` 本身可能**不存在**（不只是 .host 为空）。
    # 三元判断 `request.client.host if request.client else ...` 只挡住了
    # client 为 None 的情况，挡不住 client 属性缺失——那会 AttributeError。
    # ASGI 规范允许 client 为 None（Unix socket 场景），所以这条路径真的会被走到。
    peer = getattr(request, "client", None)
    host = getattr(peer, "host", None) if peer is not None else None
    return host or "unknown"


#: 全进程共用一个限流器。多进程部署时每个进程各限各的，
#: 总配额会被放大 N 倍——**Nginx 层按 IP 限流才是主防线，这里是兜底**。
public_limiter = RateLimiter(rate=0.2, burst=3.0)


# --------------------------------------------------------------------------
# 域名黑名单
# --------------------------------------------------------------------------
# ⚠️ 前三道闸挡的都是「技术滥用」，这一道挡的是「拿我当打手」。
#
# 场景很具体：有人嫌自己抓得慢，在我们的页面填上竞争对手的域名，
# 让**我们的服务器**去反复抓它。被投诉的是我们的 IP，
# 被 target站封的是我们的 IP，责任算运营方的。
#
# 三种来源，都落到同一个集合：
#   1. 环境变量 SEO_DENYLIST —— 运维手动加（对方发投诉邮件时最常用）
#   2. denylist.txt —— 一个域名一行，改完不用重启（每请求读一次）
#   3. 代码内置 —— 已知的高风险目标
#
# ⚠️ 每请求读文件是有意的：黑名单的意义就是「出事了立刻能加」，
# 等重启就晚了。文件不存在不是错误（首次部署没有这个文件）。
def _load_denylist() -> frozenset[str]:
    items: set[str] = set()

    raw = os.environ.get("SEO_DENYLIST", "")
    for part in raw.split(","):
        part = part.strip().lower().lstrip(".")
        if part:
            items.add(part)

    path = Path(os.environ.get("SEO_DENYLIST_FILE", "denylist.txt"))
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            # 支持 `example.com  # 理由` 的写法——三个月后你自己都忘了
            # 为什么加这条，注释是唯一的线索。
            line = line.split("#", 1)[0].strip().lower().lstrip(".")
            if line:
                items.add(line)
    except (OSError, UnicodeDecodeError):
        pass  # 文件不存在是正常的

    return frozenset(items)


def check_denied(host: str) -> None:
    """域名在黑名单里就抛 :class:`BlockedTarget`。

    ⚠️ 匹配必须**包含子域**：只挡 ``evil.com`` 的话，
    ``a.evil.com`` / ``www.evil.com`` 全部绕过。
    """
    host = host.lower().rstrip(".")
    for entry in _load_denylist():
        if host == entry or host.endswith("." + entry):
            raise BlockedTarget(f"{host} 在黑名单里")


__all__ = [
    "BlockedTarget",
    "resolve_and_check",
    "RateLimiter",
    "client_ip",
    "public_limiter",
    "check_denied",
]
