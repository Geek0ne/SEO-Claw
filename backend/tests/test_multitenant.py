"""多租户隔离。

⚠️ 这些用例是**实跑发现的两个缺陷的防回归**：

1. ``GET /sites`` 列表端点不按 owner 过滤 → tenant-a 能看到 tenant-b 的
   全部站点。而所有单租户测试（都用 local 归属）**全绿** —— 隔离缺陷
   在单租户视角下根本不可见，只有真起两个租户才现形。
2. ``HTTPException`` 在 ``BaseHTTPMiddleware`` 里抛不会被 FastAPI 的异常
   处理器接住，一路冒到 uvicorn 变成 **500** 而不是 401。默认不开鉴权时
   这条路径根本走不到，同样是实跑才炸。

所以这里全部走 HTTP 层：单测跑通不代表鉴权跑得通。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from seoclaw.main import app  # noqa: E402  （库由先导入的模块设好）

ADMIN = "test-admin-token"


def _db_path() -> str:
    """从**真实引擎**取库路径。

    ⚠️ 第一版读的是 ``os.environ["SEO_CLAW_DATABASE_URL"]``，而那是本模块
    自己设的临时库；但引擎单例早已被先导入的 test_api.py 绑到它自己的库
    上。于是我往一个根本没建表的库里 INSERT，9 个用例全 error。
    环境变量是「我请求的库」，引擎才是「实际在用的库」——要问后者。
    """
    from seoclaw.db.session import get_engine

    return str(get_engine().url.database)


def _seed_keys(rows: list[tuple[str, str]]) -> None:
    """直接往库里塞钥匙。

    ⚠️ 刻意走 sqlite3 而不是 ORM：ORM 的引擎绑在 pytest 的 event loop 上，
    在这里另起 loop 驱动会撞 "attached to a different loop"。锁库这件事
    用只读/直写的方式最省事，也最不容易写错。
    """
    from seoclaw.api.auth import new_key

    con = sqlite3.connect(_db_path())
    con.execute(
        "CREATE TABLE IF NOT EXISTS api_keys ("
        "id INTEGER PRIMARY KEY, owner TEXT, name TEXT, key_prefix TEXT,"
        " key_hash TEXT, created_at TIMESTAMP, last_used_at TIMESTAMP,"
        " revoked_at TIMESTAMP)"
    )
    for owner, name in rows:
        raw, prefix, h = new_key()
        con.execute(
            "INSERT INTO api_keys (owner,name,key_prefix,key_hash,created_at)"
            " VALUES (?,?,?,?,datetime('now'))",
            (owner, name, prefix, h),
        )
        _PLAIN[owner] = raw
        _HASHES.append(h)
    con.commit()
    con.close()


_PLAIN: dict[str, str] = {}
_HASHES: list[str] = []


@pytest.fixture()
def tenant_client(monkeypatch):
    _PLAIN.clear()
    _HASHES.clear()
    monkeypatch.setenv("SEO_CLAW_AUTH", "on")
    monkeypatch.setenv("SEO_CLAW_ADMIN_TOKEN", ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        # 引擎/表在 lifespan 里建好了，这里直接塞钥匙
        _seed_keys([("tenant-a", "a"), ("tenant-b", "b")])
        yield c


def _h(owner: str) -> dict[str, str]:
    return {"X-API-Key": _PLAIN[owner]}


# ── 门本身 ────────────────────────────────────────────────


def test_no_key_is_401_not_500(tenant_client):
    """⚠️ 这条钉的是实跑抓到的 500。

    ``HTTPException`` 在 BaseHTTPMiddleware 里抛不会被 FastAPI 接住，
    会一路冒到 uvicorn。用户看到的是「服务器错误」而不是「你没带钥匙」——
    后者让人知道该做什么，前者只让人以为程序坏了。
    """
    r = tenant_client.get("/api/v1/me")
    assert r.status_code == 401, f"期望 401，实际 {r.status_code}：{r.text[:200]}"
    assert "钥匙" in r.json()["detail"]


def test_fake_key_is_401(tenant_client):
    # ⚠️ 头值必须是 ASCII：我第一版拿「sk-seoclaw-假的」当假钥匙，
    # httpx 按 ascii 编码直接抛 UnicodeEncodeError，测试红的原因跟
    # 被测逻辑无关。
    r = tenant_client.get("/api/v1/me", headers={"X-API-Key": "sk-seoclaw-fake"})
    assert r.status_code == 401


def test_admin_token_can_mint_first_key(tenant_client):
    """⚠️ 没有这条会死锁：开鉴权后 POST /keys 自己也要求 key，
    于是没人能签发第一把钥匙。"""
    r = tenant_client.post("/api/v1/keys?name=first", headers={"X-API-Key": ADMIN})
    assert r.status_code == 201, r.text[:200]
    body = r.json()
    assert body["key"].startswith("sk-seoclaw-")
    assert "唯一一次" in body["warning"]


def test_single_user_mode_needs_no_key(monkeypatch):
    """自部署单机（未开鉴权）不该有任何门槛。"""
    monkeypatch.setenv("SEO_CLAW_AUTH", "off")
    with TestClient(app, raise_server_exceptions=False) as c:
        me = c.get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["auth_enabled"] is False


# ── 钥匙不落明文 ──────────────────────────────────────────


def test_plaintext_key_never_stored(tenant_client):
    """⚠️ 库被拖走时攻击者拿到的应只是哈希。存明文的话，
    一次 SQL 注入就等于交出所有租户的钥匙。"""
    r = tenant_client.post("/api/v1/keys?name=leak", headers={"X-API-Key": ADMIN})
    plaintext = r.json()["key"]

    con = sqlite3.connect(_db_path())
    rows = con.execute("SELECT key_hash, key_prefix FROM api_keys").fetchall()
    con.close()

    for key_hash, _prefix in rows:
        assert plaintext not in key_hash, "库里出现了明文钥匙"
        assert len(key_hash) == 64, "应当是 sha256 长度"


def test_key_hash_is_stable_and_long_enough():
    """列表接口只回前缀 —— 完整钥匙不在库里，也没有理由展示。"""
    from seoclaw.api.auth import hash_key, new_key

    raw, prefix, h = new_key()
    assert raw.startswith(prefix)
    assert h != raw and len(h) == 64
    assert hash_key(raw) == h, "同一把钥匙哈希必须稳定，否则每次请求都认不出"


# ── 隔离：这条是那个真漏洞的防回归 ────────────────────────


def test_site_list_is_scoped_to_owner(tenant_client):
    """⚠️ 实跑逮到的越权：列表端点没按 owner 过滤，两个租户互相看到对方的站。

    单站点硬闯是 404（当时是对的），列表整片泄露 —— 而单租户测试全绿。
    """
    tenant_client.post("/api/v1/sites", headers=_h("tenant-a"),
                       json={"domain": "a.example"})
    tenant_client.post("/api/v1/sites", headers=_h("tenant-b"),
                       json={"domain": "b.example"})

    a = [s["domain"] for s in tenant_client.get("/api/v1/sites", headers=_h("tenant-a")).json()]
    b = [s["domain"] for s in tenant_client.get("/api/v1/sites", headers=_h("tenant-b")).json()]

    assert "a.example" in a and "b.example" not in a, f"tenant-a 看到了别人的：{a}"
    assert "b.example" in b and "a.example" not in b, f"tenant-b 看到了别人的：{b}"


def test_cross_tenant_site_access_is_404(tenant_client):
    """⚠️ 必须是 404 而不是 403。

    403 等于告诉对方「这个站存在，只是你没权限」—— 那本身就是信息泄露，
    与「不存在」不可区分才是对的。
    """
    site = tenant_client.post("/api/v1/sites", headers=_h("tenant-a"),
                              json={"domain": "secret.example"}).json()
    r = tenant_client.get(f"/api/v1/sites/{site['id']}", headers=_h("tenant-b"))
    assert r.status_code == 404, f"期望 404，实际 {r.status_code}"


def test_created_site_belongs_to_caller(tenant_client):
    """建站时必须写 owner。列的默认值是 local —— 靠默认的话，
    SaaS 模式下新建的站会落到 local 归属，租户自己都看不到。"""
    s = tenant_client.post("/api/v1/sites", headers=_h("tenant-a"),
                           json={"domain": "owned.example"}).json()
    assert s["id"]
    con = sqlite3.connect(_db_path())
    owner = con.execute("SELECT owner FROM sites WHERE id=?", (s["id"],)).fetchone()[0]
    con.close()
    assert owner == "tenant-a", f"归属写错了：{owner}"


# ── 额度 ──────────────────────────────────────────────────


def test_quota_reported_per_tenant(tenant_client):
    me = tenant_client.get("/api/v1/me", headers=_h("tenant-a")).json()
    assert me["auth_enabled"] is True
    assert me["quota"]["limit"] == 2000
    assert me["quota"]["enforced"] is True, "SaaS 模式必须真的计量"
    assert me["quota"]["used"] == 0


def test_single_user_mode_is_not_limited(monkeypatch):
    """自部署单机不计量 —— 灰度阶段不拦。"""
    monkeypatch.setenv("SEO_CLAW_AUTH", "off")
    monkeypatch.delenv("SEO_CLAW_FREE_PAGES", raising=False)
    with TestClient(app, raise_server_exceptions=False) as c:
        q = c.get("/api/v1/me").json()["quota"]
        assert q["enforced"] is False and q["limit"] is None
