"""check_meta 的守卫行为回归（2026-10-25 SSRF 修复）。

只测守卫分支，不发真网络请求：monkeypatch 掉 guard 的两个入口与
httpx.Client，断言三种映射——拒绝→no、解析失败→unknown、放行→照旧。
被拒/解析失败还发起请求的，直接让用例红（fail()）。
"""
import pytest

from seoclaw.api import verification as V
from seoclaw.web.guard import BlockedTarget


class _FakeResp:
    status_code = 200
    text = '<meta name="seo-claw-verification" content="sc-tok">'


class _FakeClient:
    """替身 Client：记录是否真的发起了请求，供用例断言。"""

    requested = False

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        type(self).requested = True
        return _FakeResp()


@pytest.fixture()
def fake_client(monkeypatch):
    _FakeClient.requested = False
    monkeypatch.setattr("seoclaw.api.verification.httpx.Client", _FakeClient)
    return _FakeClient


def _patch_guard(monkeypatch, resolve_behavior):
    monkeypatch.setattr("seoclaw.web.guard.check_denied", lambda host: None)
    monkeypatch.setattr("seoclaw.web.guard.resolve_and_check", resolve_behavior)


def test_blocked_reserved_ip_is_no(monkeypatch, fake_client):
    """目标解析进保留网段 → 明确 no，且绝不该发起请求。"""
    def boom(url, **kw):
        raise BlockedTarget(f"{url} 解析到保留网段，拒绝")

    _patch_guard(monkeypatch, boom)
    r = V.check_meta("internal.example", "sc-tok")
    assert fake_client.requested is False, "被拒目标不应发起请求"
    assert r.verdict == "no"
    assert "安全策略拒绝" in r.detail


def test_dns_failure_is_unknown(monkeypatch, fake_client):
    """解析失败 ≠ 不存在（模块口径）：归 unknown，不发起请求。"""
    def boom(url, **kw):
        raise BlockedTarget("域名解析失败：Name or service not known")

    _patch_guard(monkeypatch, boom)
    r = V.check_meta("gone.example", "sc-tok")
    assert fake_client.requested is False, "解析失败不应发起请求"
    assert r.verdict == "unknown"


def test_allowed_target_still_fetches(monkeypatch, fake_client):
    """放行目标照旧抓首页并对上 token。"""
    _patch_guard(monkeypatch, lambda url, **kw: url)
    r = V.check_meta("ok.example", "sc-tok")
    assert fake_client.requested is True
    assert r.verdict == "yes"
