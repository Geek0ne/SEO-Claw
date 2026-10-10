"""SSRF 拦截与限流的测试。

## 为什么这组测试要用真实 IP 字面量，不 mock

SSRF 的整个意义就是「拦住某个具体地址」。用 mock 打桩就没有意义了——
测出来的绿不能说明真拦住了。这里的样本都是**真实存在的地址段**，
`127.0.0.1`、`169.254.169.254`、`10.0.0.1` 不需要联网就能判定。

唯一需要 DNS 的那一条（公共域名）单独放行并标注理由。

## 攻击者视角：每个用例先写「我能怎么打」

用例命名就是攻击手法。这样将来有人放宽某条规则时，
会立刻看到「这么一放宽，攻击手法 XXX 就通了」。
"""

from __future__ import annotations

import pytest

from seoclaw.web.guard import (
    BlockedTarget,
    RateLimiter,
    client_ip,
    resolve_and_check,
)


# --------------------------------------------------------------------------
# SSRF：每一条都是一个攻击手法
# --------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",                    # 打自己的服务
    "http://127.0.0.1:8000/api/v1/health",   # 带端口也一样
    "http://localhost/",                     # 主机名别名
    "http://169.254.169.254/latest/meta-data/",  # 偷 IAM 凭据 ← 最致命
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://10.0.0.1/",                      # 云内网
    "http://172.16.0.1/",                    # 私有网段
    "http://192.168.1.1/",                   # 路由器管理页
    "http://0.0.0.0/",                       # 全零，等价回环
])
def test_literal_internal_ip_blocked(url):
    """手法 1：直接填内网 IP。"""
    with pytest.raises(BlockedTarget):
        resolve_and_check(url)


@pytest.mark.parametrize("url,scheme", [
    ("file:///etc/passwd", "file"),        # 读本地文件
    ("gopher://127.0.0.1:11211/_stats", "gopher"),  # 攻击 memcached
    ("ftp://example.com/", "ftp"),
])
def test_non_http_scheme_blocked(url, scheme):
    """手法 2：换协议。

    ``gopher://`` 是 SSRF 的经典放大器——借服务端去打 Redis/memcached，
    而这些协议往往只认内网地址。
    """
    with pytest.raises(BlockedTarget) as exc:
        resolve_and_check(url)
    assert scheme in str(exc.value)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:22/",     # SSH
    "http://10.0.0.1:6379/",    # Redis
    "http://10.0.0.1:3306/",    # MySQL
    "http://10.0.0.1:27017/",   # MongoDB
    "http://10.0.0.1:9200/",    # Elasticsearch
])
def test_database_port_blocked(url):
    """手法 3：目标地址正常，但打数据库端口。

    只拦 IP 不够——公网可达的数据库也要挡。
    """
    with pytest.raises(BlockedTarget):
        resolve_and_check(url)


def test_cloud_metadata_hostname_blocked():
    """手法 4：用云厂商的主机名而非 IP，绕开基于 IP 的判断。"""
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://metadata.google.internal/computeMetadata/v1/")


def test_ipv6_loopback_blocked():
    """手法 5：IPv6 回环。很多守卫只写了 IPv4。"""
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://[::1]/")


def test_ipv4_mapped_ipv6_blocked():
    """手法 6：IPv4-mapped IPv6（::ffff:127.0.0.1）。

    ⚠️ 这是个真实绕过点：某些 IPv6 实现下
    ``ipaddress.IPv6Address('::ffff:127.0.0.1').is_loopback`` 返回 False，
    所以只查 is_loopback 会漏。guard 里显式解包 ipv4_mapped 再判一次。
    """
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://[::ffff:127.0.0.1]/")


def test_ipv6_link_local_blocked():
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://[fe80::1]/")


def test_public_literal_ip_allowed():
    """手法 7（反向）：守卫不能把正常用户也拦了。

    1.1.1.1 是公网地址，必须放行——否则守卫就是个纯障碍。
    """
    assert resolve_and_check("http://1.1.1.1/")


def test_dns_rebinding_detected():
    """手法 8：DNS rebinding。

    构造一个「同时返回公网 IP 和内网 IP」的解析结果。
    ⚠️ guard 必须核对**全部** A 记录——只看第一个就等于没做，
    因为攻击者可以随便调整记录顺序。

    这里 mock 掉 getaddrinfo，不真发请求。
    """
    import socket

    import seoclaw.web.guard as guard

    def _fake(host, port, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80)),
        ]

    orig = socket.getaddrinfo
    socket.getaddrinfo = _fake
    try:
        with pytest.raises(BlockedTarget) as exc:
            guard.resolve_and_check("http://evil.test/")
        assert "127.0.0.1" in str(exc.value)
    finally:
        socket.getaddrinfo = orig


def test_empty_dns_result_blocked():
    """手法 9：DNS 解析不出东西——不能当成「没事，放行」。"""
    import socket

    import seoclaw.web.guard as guard

    orig = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **k: []
    try:
        with pytest.raises(BlockedTarget):
            guard.resolve_and_check("http://empty.test/")
    finally:
        socket.getaddrinfo = orig


def test_dns_failure_blocked():
    """域名不存在要报「解析失败」，不能抛裸异常。"""
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://this-domain-should-not-exist-seoclaw-test.invalid/")


def test_missing_hostname_blocked():
    with pytest.raises(BlockedTarget):
        resolve_and_check("http://")


# --------------------------------------------------------------------------
# 限流
# --------------------------------------------------------------------------


def test_burst_then_throttle():
    """手法 10：拿到突发额度后立刻开始撞墙。

    burst=3 表示前 3 次放行，第 4 次必须被拒，且给出等待秒数。
    """
    rl = RateLimiter(rate=1.0, burst=3.0)
    for i in range(3):
        ok, _ = rl.allow("1.2.3.4")
        assert ok, f"第 {i+1} 次应放行（突发额度内）"
    ok, retry = rl.allow("1.2.3.4")
    assert not ok, "第 4 次必须被拒"
    assert retry > 0, "被拒时必须告诉客户端等多久"


def test_ips_are_independent():
    """手法 11：换一个 IP 重置额度——所以限流不能只看总量。"""
    rl = RateLimiter(rate=0.001, burst=2.0)
    for _ in range(2):
        rl.allow("1.1.1.1")
    assert not rl.allow("1.1.1.1")[0], "A 耗尽"
    assert rl.allow("2.2.2.2")[0], "B 不该受 A 影响"


def test_refill_over_time():
    """令牌桶必须真的会回补，否则封禁是永久的。"""
    import time

    rl = RateLimiter(rate=10.0, burst=2.0)
    for _ in range(2):
        rl.allow("1.1.1.1")
    assert not rl.allow("1.1.1.1")[0]
    time.sleep(0.3)  # 10/秒 * 0.3 = 3 个令牌，够补满
    assert rl.allow("1.1.1.1")[0], "等一会就该恢复了"


def test_bucket_count_bounded():
    """手法 12：伪造海量 IP 撑爆内存。

    bucket 数量必须有上限，否则一个脚本就能吃掉几个 G。
    """
    rl = RateLimiter(rate=1.0, burst=1.0)
    rl._max_keys = 50
    for i in range(500):
        rl.allow(f"10.0.{i // 256}.{i % 256}")
    assert len(rl._buckets) <= 100, f"内存泄漏：{len(rl._buckets)} 个桶"


# --------------------------------------------------------------------------
# client_ip
# --------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, headers=None, host="1.1.1.1"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_uses_rightmost_xff():
    """⚠️ **取最右边**而不是最左边。

    最左边是任何人都能自己伪造的（直接发一个
    ``X-Forwarded-For: 9.9.9.9``）。取最左边的话限流就是摆设。
    """
    r = _FakeRequest({"x-forwarded-for": "9.9.9.9, 1.2.3.4, 5.6.7.8"})
    assert client_ip(r) == "5.6.7.8"


def test_client_ip_single_xff_value():
    r = _FakeRequest({"x-forwarded-for": "1.2.3.4"})
    assert client_ip(r) == "1.2.3.4"


def test_client_ip_falls_back_to_peer():
    r = _FakeRequest({}, host="192.0.2.1")
    assert client_ip(r) == "192.0.2.1"


def test_client_ip_handles_missing_peer():
    class _NoClient:
        headers: dict = {}

    assert client_ip(_NoClient()) == "unknown"


# --------------------------------------------------------------------------
# 域名黑名单
# --------------------------------------------------------------------------
#
# ⚠️ 这一道挡的不是技术滥用，是「拿我当打手」：
# 有人嫌自己抓得慢，在我们的页面填上竞争对手的域名，
# 让**我们的服务器**去反复抓它。被投诉的是我们的 IP，
# 被目标站封的也是我们的 IP，责任算运营方的。


def test_denylist_from_env(monkeypatch):
    """手法 14：对手发投诉邮件，运维当场加进环境变量。"""
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", "competitor.test, other.test")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    with pytest.raises(BlockedTarget):
        guard.check_denied("competitor.test")


def test_denylist_blocks_subdomains(monkeypatch):
    """⚠️ 必须连子域一起挡。

    只挡 ``evil.com`` 的话 ``www.evil.com`` / ``a.b.evil.com`` 全部绕过
    —— 而攻击者只要多打两个字符就逃出去了。
    """
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", "evil.test")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    for host in ("evil.test", "www.evil.test", "a.b.evil.test"):
        with pytest.raises(BlockedTarget):
            guard.check_denied(host)


def test_denylist_from_file(tmp_path, monkeypatch):
    """手法 15：改文件不用重启——出事时最看重这一点。

    黑名单的意义就是「立刻能加」，等重启就晚了。
    """
    import seoclaw.web.guard as guard
    f = tmp_path / "denylist.txt"
    f.write_text(
        "# 对方 2026-10-03 发投诉邮件要求停止\n"
        "spammer.test\n"
        "\n"
        "  spaced.test  # 行内注释也要能剥\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SEO_DENYLIST", "")
    monkeypatch.setenv("SEO_DENYLIST_FILE", str(f))

    for host in ("spammer.test", "spaced.test"):
        with pytest.raises(BlockedTarget):
            guard.check_denied(host)


def test_denylist_case_and_dot_insensitive(monkeypatch):
    """大小写 / 前导点 / 结尾点都要归一，否则白名单式绕过。"""
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", ".EVIL.test")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    with pytest.raises(BlockedTarget):
        guard.check_denied("Evil.Test")


def test_denylist_does_not_block_lookalikes(monkeypatch):
    """⚠️ 不能误伤：挡的是 evil.test，不能连 notevil.test 也挡了。

    用 ``endswith(entry)`` 而不是 ``endswith("." + entry)`` 就会误伤。
    """
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", "evil.test")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    for ok in ("notevil.test", "evil.test.other.com", "example.test"):
        guard.check_denied(ok)  # 不该抛


def test_missing_denylist_file_is_not_an_error(monkeypatch):
    """首次部署没有这个文件是正常的，不能因此 500。"""
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", "")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    guard.check_denied("anything.test")  # 不该抛


def test_empty_denylist_allows_everything(monkeypatch):
    """没有配置时不能变成「全部拒绝」——那等于服务直接不可用。"""
    import seoclaw.web.guard as guard
    monkeypatch.setenv("SEO_DENYLIST", "   ,  ,")
    monkeypatch.setenv("SEO_DENYLIST_FILE", "/nonexistent/denylist.txt")
    guard.check_denied("example.test")
