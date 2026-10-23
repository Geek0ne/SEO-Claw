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

import hashlib
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


def _seed_keys(client, rows: list[tuple[str, str]]) -> None:
    """**通过应用自己的 API** 建钥匙。

    ⚠️ **为什么不用裸 sqlite3 直写**（第一版是那么写的）：
    裸连接与应用引擎的 aiosqlite 连接是**两个连接**，在同一个库文件上
    争写锁。而 TestClient 的 lifespan 跑在**另一个线程**的 event loop 里
    （starlette 用 anyio 的 BlockingPortal），于是「应用侧持着锁」与
    「测试侧要写」是**真并发**——撞上就报
    ``sqlite3.OperationalError: database is locked``。

    ⚠️ 症状极具迷惑性：**单跑这个模块全绿，全量跑随机红**（同一份代码
    连跑 8 轮，有 2 轮报 2 个 error）。PLAN.md 技术债里记的就是这件事，
    此前一直误判成「多模块共用一个库」，绕了一大圈。

    ⚠️ **别用 busy_timeout / retry 糊**：实测给两侧都加 timeout=5 之后，
    失败轮次耗时从 45s 涨到 114s（真的在等锁等到超时），而问题一个没少。
    PLAN.md 原先就警告过「别用 retry 掩盖」。

    ✅ **正解是消除第二个连接**：改用 ``POST /api/v1/keys``——
    走应用自己的会话与连接，全程**只有一个连接**在写这个库，
    锁竞争从根上不存在。
    顺带的好处：这条路**真的走了一遍生产用的签发流程**
    （含 owner 归属、哈希落库），比直写 INSERT 更接近真实行为——
    原先那种「手工 INSERT 出来的钥匙」其实绕过了生产代码路径。
    """
    for owner, name in rows:
        # ⚠️ 用管理令牌 + x-owner 头指定归属：auth.py 里管理令牌支持
        # 「以任意 owner 身份操作」，这正是多租户测试要的。
        r = client.post(
            "/api/v1/keys",
            params={"name": name},
            headers={"X-API-Key": ADMIN, "x-owner": owner},
        )
        assert r.status_code == 201, f"签发钥匙失败：{r.status_code} {r.text[:200]}"
        raw = r.json()["key"]
        _PLAIN[owner] = raw
        _HASHES.append(hashlib.sha256(raw.encode()).hexdigest())


_PLAIN: dict[str, str] = {}
_HASHES: list[str] = []


@pytest.fixture()
def tenant_client(monkeypatch):
    _PLAIN.clear()
    _HASHES.clear()
    monkeypatch.setenv("SEO_CLAW_AUTH", "on")
    monkeypatch.setenv("SEO_CLAW_ADMIN_TOKEN", ADMIN)
    with TestClient(app, raise_server_exceptions=False) as c:
        # ⚠️ 顺序要紧：**先建钥匙，再清站点**——清理要走 DELETE 端点，
        # 而那需要对应租户的钥匙（否则 404）。
        # ⚠️ 建钥匙走应用自己的 API（见 _seed_keys 的注释）：全程只有
        # 一个连接在写这个库，锁竞争从根上不存在。
        _seed_keys(c, [("tenant-a", "a"), ("tenant-b", "b")])
        # ⚠️ 站点数据要在**每个用例前**清干净。
        #
        # 原因：引擎是全局单例，库文件也是同一个——上一个用例建的站点
        # 还在表里，于是下一个用例建同名域名就撞 409
        # （"同域不重复建站"是产品要求的行为，测试里要自己保证前置干净）。
        # 症状是「用例之间互相影响」，而报错点（409）离原因（上个用例
        # 留下的数据）很远——所以这里显式清。
        _clear_sites(c)
        yield c


def _clear_sites(client) -> None:
    """清空站点表（每个用例开始前）。

    ⚠️ **走应用自己的 API**（``DELETE /sites/{id}``）而不是直接执行 SQL：
    直接 SQL 需要在应用的 event loop 里跑（``client.portal.call``），
    那个 loop 正在处理请求——交错之下会出现「刚清完又写进去」这类
    说不清的时序问题。走 API 则完全串行，且用的是产品自己的删除逻辑
    （带级联与归属校验）。

    ⚠️ 归属校验怎么办：删除要用对应租户的头，否则 404。
    这里逐个租户试——建站时用的就是这些租户。
    """
    for owner in ("tenant-a", "tenant-b"):
        headers = _h(owner)
        for site in client.get("/api/v1/sites", headers=headers).json():
            client.delete(f"/api/v1/sites/{site['id']}", headers=headers)


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

    # ⚠️ 用**只读模式**打开（``mode=ro``）：这样连文件锁都不碰。
    # 这两处是**读**——不写就不会与应用侧争写锁，但只读模式更保险，
    # 而且它还顺带证明了「读不干扰写」这件事本身。
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5)
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
    # ⚠️ 只读模式打开（``mode=ro``）——不碰文件锁，理由见上一处。
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5)
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
