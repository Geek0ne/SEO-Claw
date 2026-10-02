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


def same_url_ignoring_path_case(a: str, b: str) -> bool:
    """忽略 path 大小写后是否同一个 URL。

    与 `same_url` 的区别：这里**不修改** normalize_url 的语义。
    path 按 URL 规范是区分大小写的，`/Foo` 和 `/foo` 理论上是两个资源，
    所以不能让 `normalize_url` 直接把 path 小写化——那会让真正指向
    不同页面的 canonical 混过去，漏报真冲突。

    本函数只用于「差异**仅**来自 path 大小写」这一种窄场景的识别，
    让调用方把它降级成提示，而不是当成权重转移问题。
    """
    na, nb = normalize_url(a), normalize_url(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return na.lower() == nb.lower()


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


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def same_site_scope(url: str | None, base_domain: str) -> bool:
    """该 URL 是否属于「本次扫描的主站」——**不含兄弟子域**。

    为什么不能直接用 is_internal()：它按可注册域判断，
    us.checkout.gymshark.com 和 gymshark.com 同属 gymshark.com，算站内。
    对内链权重传递这是对的，对「给这个站打健康分」就错了。

    实测代价：gymshark.com 扫描 25 页里 24 页是 us.checkout.gymshark.com，
    124 条问题有 119 条来自子域，于是主站被判 0.0 分。结账页带 noindex
    是**正确配置**，却被报成 CRITICAL「页面被屏蔽收录」——规则判得对、
    用户照做反而更糟。vitejs.dev 同理：24 条问题全在 ja/v2/registry 子域，
    剔掉后 94.2 → 100.0。

    所以口径必须是：host 完全相同，或仅差 www 前缀。
    """
    if not url:
        return False
    # 用 hostname 而非 netloc：netloc 带端口（gymshark.com:443），
    # 剥离 www 之后仍与 gymshark.com 不相等，会把本站误判成站外。
    host = (urlparse(url).hostname or "").lower().strip(".")
    base = (base_domain or "").split(":")[0].lower().strip(".")
    if not host or not base:
        return False
    return _strip_www(host) == _strip_www(base)


# --------------------------------------------------------------------------
# CJK 字符判定（技术债 #3：原先有 4 份重复实现，语义还不一致）
#
# ⚠️ 刻意拆成**两个**函数而不是一个大开关。
# 重复的根因不是「写得不好」，而是**调用点要的本来就不是同一件事**：
#
#   contains_han()  —— 只要汉字。用于「这是不是中文内容」
#                       （百度规则包、微信生态规则包）。
#                       ⚠️ 这里**不能**收谚文：谚文命中会让韩语站
#                       进入中文生态规则，产生一批新误报。
#
#   contains_cjk()  —— 全 CJK 书写体系（汉字/扩展A/假名/谚文/
#                       CJK 标点/全角）。用于「这标题是不是全角排版」
#                       （base 的 30 vs 60 阈值）、语言构成比、URL 判定。
#
# 早先 base/baidu/cnh_eco/google 各自抄了一份 `_is_cjk`，
# 其中只有 google 那份是全范围 —— 于是同一份「CJK 判定」在库里
# 有四种行为。合并时若统一成宽版，上面三个语义窄的调用点会被改变行为；
# 统一成窄版，全角标题又会被按半角阈值判。
# --------------------------------------------------------------------------

#: 汉字（含扩展 A 与兼容表意文字）
_HAN_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))

#: 全 CJK 书写体系 = 汉字 + 假名 + 谚文 + CJK 标点 + 全角形式
_CJK_RANGES = _HAN_RANGES + (
    (0x3040, 0x30FF),  # 平假名 / 片假名
    (0xAC00, 0xD7AF),  # 谚文音节
    (0x3000, 0x303F),  # CJK 标点（含全角句读）
    (0xFF00, 0xFF60),  # 全角形式
)


def _in_ranges(ch: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def contains_han(text: str) -> bool:
    """是否含**汉字**。用于判定「是不是中文内容」。

    刻意不收假名与谚文：日文/韩文内容不该被中文生态规则接管
    （baidu 包另有 ``_is_japanese`` 守卫，但根上就不该进来）。
    """
    return any(_in_ranges(ch, _HAN_RANGES) for ch in (text or ""))


def cjk_ratio(text: str) -> float:
    """汉字占比（0~1）。空串返回 0.0。"""
    if not text:
        return 0.0
    return sum(1 for ch in text if _in_ranges(ch, _HAN_RANGES)) / len(text)


def contains_cjk(text: str) -> bool:
    """是否含任一 CJK 字符（含假名、谚文、全角）。用于排版/语言构成判定。"""
    return any(_in_ranges(ch, _CJK_RANGES) for ch in (text or ""))


def is_cjk_char(ch: str) -> bool:
    """单字符版（google 包的字符构成比按字符逐个判断，用这个）。"""
    return bool(ch) and _in_ranges(ch, _CJK_RANGES)
