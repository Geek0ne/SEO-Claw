"""通用工具：URL 归一化与相等性判断。

URL 比较是整个产品的隐性基础——canonical 判断、断点续传去重、
站点级重复检测都依赖它。规则错误会传导成大量误报，所以单独抽出来。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

# 跟踪类参数：比较 URL 时应忽略，否则 a?utm_source=x 与 a?utm_source=y
# 会被当成两个不同页面
TRACKING_PARAM_PREFIXES = ("utm_",)


def normalize_url(url: str) -> str:
    """归一化 URL：忽略协议、www、末尾斜杠与跟踪参数。

    用于判断两个 URL 是否指向同一资源。
    """
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    path = (parsed.path or "/").rstrip("/") or "/"
    # 合并尾斜杠与 index.html 的等价形式
    if path.endswith("/index.html"):
        path = path[: -len("/index.html")] or "/"
    elif path.endswith("index.html"):
        path = path[: -len("index.html")] or "/"

    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    query = urlencode(sorted(kept))
    return f"{host}{path}" + (f"?{query}" if query else "")


def same_url(a: str, b: str) -> bool:
    return normalize_url(a) == normalize_url(b) and normalize_url(a) != ""


def registrable_domain(host: str) -> str:
    """粗略取可注册域，判断站内/站外链接。

    不处理完整公共后缀表（com.cn / co.uk 等只覆盖常见几种），
    对判断内链足够；需要严格判断时再引入 tldextract。
    """
    host = (host or "").lower().strip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level_suffixes = {"com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "co.uk", "co.jp"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in two_level_suffixes:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_internal(href: str, base_domain: str) -> bool:
    """href 是否指向本站（含子域）。"""
    host = urlparse(href).netloc
    if not host:
        return False
    base = registrable_domain(base_domain)
    target = registrable_domain(host)
    return bool(base) and target == base
