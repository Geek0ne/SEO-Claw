"""租户鉴权：一把钥匙 → 一个归属。

## 为什么默认「关」

聂董现在这台机器是**单用户自部署**。这时若强制要 key，等于给唯一的使用者
加一道没有意义的门槛，还会在他第一次打开 Web 时看到一个「请填 API Key」
的空页面 —— 而他并没有第二个用户。所以：

    SEO_CLAW_AUTH=off（默认）  → 一切归属 local，不校验 key
    SEO_CLAW_AUTH=on           → 必须带 X-API-Key，否则 401

⚠️ 这不是「后门」，是**单机模式与 SaaS 模式共用一套数据**的结果：
`sites.owner` 默认就是 "local"，所以关掉鉴权时不需要第二份数据、不需要
迁移老数据。将来开 SaaS 只是把这个开关打开。

## key 只存哈希

明文只在创建那一刻返回一次。丢了只能重发不能找回 —— 这是有意的代价：
存明文的话，一次 SQL 注入就等于交出所有租户的钥匙。
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request

from ..db import models as m
from ..db.session import get_session_factory

#: 单机模式下所有数据的归属
LOCAL_OWNER = "local"

#: 明文前缀。带上它便于在日志/粘贴时一眼认出，且泄露面比裸随机串小
KEY_PREFIX = "sk-seoclaw-"


def auth_enabled() -> bool:
    return os.getenv("SEO_CLAW_AUTH", "off").strip().lower() in ("on", "1", "true", "yes")


def new_key() -> tuple[str, str, str]:
    """生成一把 key，返回 ``(明文, 前缀, 哈希)``。

    ⚠️ 明文只在这里出现一次，之后库里只有哈希。
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:16], hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Auth:
    owner: str
    enabled: bool

    def owns(self, site) -> bool:
        """⚠️ 单机模式永远为真 —— 没有第二个用户，谈归属没有意义。"""
        if not self.enabled:
            return True
        return getattr(site, "owner", LOCAL_OWNER) == self.owner


async def resolve(request: Request) -> Auth:
    """从请求头解析归属。"""
    if not auth_enabled():
        return Auth(owner=LOCAL_OWNER, enabled=False)

    raw = (
        request.headers.get("x-api-key")
        or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    )
    if not raw:
        raise HTTPException(
            status_code=401,
            detail="缺少访问钥匙。请在请求头带 X-API-Key，或在 Web 界面右上角设置。",
        )

    # ⚠️ 管理令牌：开鉴权后的**唯一**入口。
    # 没有它会死锁：开 SEO_CLAW_AUTH=on 之后 POST /keys 自己也要求 key，
    # 于是没人能签发第一把钥匙。
    # 刻意做成「显式环境变量」而不是「库里一把 key 都没有时免费放行」——
    # 后者会让部署后到第一把 key 生成之间存在一个**竞态窗口**，
    # 谁先跑到谁拿走整个实例的管理权。
    admin = os.getenv("SEO_CLAW_ADMIN_TOKEN", "").strip()
    if admin and secrets.compare_digest(raw, admin):
        owner = request.headers.get("x-owner") or LOCAL_OWNER
        return Auth(owner=owner[:64], enabled=True)

    key_hash = hash_key(raw)
    async with get_session_factory()() as session:
        from sqlalchemy import select

        row = (await session.execute(
            select(m.ApiKey).where(m.ApiKey.key_hash == key_hash)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=401, detail="钥匙无效。")
        if row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="这把钥匙已被撤销。")

        row.last_used_at = m.func.now()
        await session.commit()
        return Auth(owner=row.owner, enabled=True)


def guard(auth: Auth, site) -> None:
    """站点不属于当前归属 → 404 而不是 403。

    ⚠️ 回 403 等于告诉别人「这个站点存在，只是你没权限」—— 那本身
    就是信息泄露。统一回 404，与「不存在」不可区分。
    """
    if not auth.owns(site):
        raise HTTPException(status_code=404, detail="站点不存在。")


# ══════════════════════════════════════════════════════════
# 接线：中间件 + ContextVar
# ══════════════════════════════════════════════════════════
#
# ⚠️ 为什么用 ContextVar 而不是给每个端点加 auth 参数：
# 站点相关端点有 15 个，每个都加一个参数意味着以后新增端点时
# **忘了加就会静默越权** —— 而漏掉的那一个不会报错，只会放行。
# 做成中间件后鉴权只发生在一处，端点即使忘了声明也照样受管。

from contextvars import ContextVar  # noqa: E402

_current: ContextVar[Optional[Auth]] = ContextVar("seoclaw_auth", default=None)


def current_auth() -> Auth:
    """当前请求的归属。中间件之外调用（如脚本、CLI）→ 单机 local。"""
    return _current.get() or Auth(owner=LOCAL_OWNER, enabled=False)


async def auth_middleware(request: Request, call_next):
    # ⚠️ 这里必须自己把 HTTPException 变成响应。
    # FastAPI/Starlette 的异常处理器只在**路由内**生效；外层中间件抛出的
    # HTTPException 不会被它接住，会一路冒到 uvicorn 变成 **500**。
    # 我第一版就是 `auth = await resolve(request)` 直接抛 —— 单测全绿
    # （单测默认不开鉴权），真开鉴权后「没带钥匙」返回 500 而不是 401。
    try:
        auth = await resolve(request)
    except HTTPException as exc:
        from starlette.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={"WWW-Authenticate": "ApiKey"} if exc.status_code == 401 else None,
        )

    token = _current.set(auth)
    try:
        return await call_next(request)
    finally:
        _current.reset(token)
