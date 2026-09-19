"""通过 GitCode 登录（OAuth 2.0 授权码模式）。

流程：
  1. GET /api/auth/gitcode/start            → 种一个防 CSRF 的 state cookie，跳去 GitCode 授权页
  2. GitCode 回调 /api/auth/gitcode/callback → 校验 state，用 code 换 access_token，取用户资料
  3. 按 GitCode 用户 id 找本地账号：找到就登录，没找到就建一个（无密码账号）

两种用途共用同一套跳转：
  - purpose=login  普通登录
  - purpose=bind   已登录用户把自己的账号和 GitCode 绑定（避免同一人出现两个账号）

凭据来自环境变量 / .env：GITCODE_CLIENT_ID、GITCODE_CLIENT_SECRET。
没配就不显示 GitCode 登录入口，接口返回 503。
"""
from __future__ import annotations

import hmac
import re
import sqlite3
from typing import Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..config import (DEFAULT_SCOPE, authorize_url, env, gitcode_client,
                      gitcode_enabled, gitcode_redirect_uri,
                      http_client_kwargs, token_url, user_api)
from ..db import get_db, utcnow
from ..deps import (create_session, get_current_user, lookup_session,
                    set_session_cookie)
from ..security import NO_PASSWORD, new_token

router = APIRouter(prefix="/api/auth/gitcode", tags=["gitcode"])

OAUTH_COOKIE = "ml_oauth"
STATE_TTL = 600          # 10 分钟足够走完授权
_USERNAME_RE = re.compile(r"[^a-z0-9_-]+")


def _require_configured() -> tuple[str, str]:
    if not gitcode_enabled():
        raise HTTPException(
            status_code=503,
            detail="还没有配置 GitCode 登录：请在 .env 里填 GITCODE_CLIENT_ID / GITCODE_CLIENT_SECRET")
    return gitcode_client()


def _safe_username(login: str) -> str:
    """把 GitCode 的 login 变成合法的本地用户名。"""
    name = _USERNAME_RE.sub("-", (login or "").strip().lower()).strip("-_")
    name = name[:24] or "gitcode-user"
    return name


def _unique_username(conn: sqlite3.Connection, base: str) -> str:
    candidate, n = base, 1
    while conn.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE",
                       (candidate,)).fetchone():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@router.get("/status")
def status():
    """登录页用它决定要不要显示 GitCode 按钮。"""
    cid, _ = gitcode_client()
    return {"enabled": gitcode_enabled(), "client_id": cid or None}


@router.get("/start")
def start(request: Request, purpose: str = "login",
          conn: sqlite3.Connection = Depends(get_db)):
    """跳到 GitCode 授权页。

    登录用途不需要已登录；绑定用途需要（这里手动校验，不用依赖注入，
    否则未登录时会在配置检查之前就被 401 拦下，报错信息会误导）。
    """
    _require_configured()
    if purpose not in ("login", "bind"):
        raise HTTPException(status_code=400, detail="purpose 只能是 login 或 bind")

    target_id = ""
    if purpose == "bind":
        user = lookup_session(conn, request)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录再绑定 GitCode")
        target_id = str(user["id"])

    state = new_token()
    params = {
        "client_id": gitcode_client()[0],
        "redirect_uri": gitcode_redirect_uri(request),
        "response_type": "code",
        "scope": env("GITCODE_SCOPE", DEFAULT_SCOPE),
        "state": state,
    }
    resp = RedirectResponse(f"{authorize_url()}?{urlencode(params)}", status_code=302)
    resp.set_cookie(OAUTH_COOKIE, f"{state}|{purpose}|{target_id}",
                    max_age=STATE_TTL, httponly=True, samesite="lax", path="/")
    return resp


def _fail(message: str) -> RedirectResponse:
    """出错就回到应用入口，把原因放在查询串里。

    不带 hash：由前端按「已登录/未登录」决定是显示在登录页上还是弹 toast。
    绑定失败时用户是已登录状态，如果硬跳 #/login 会被重定向到工作台，报错就丢了。
    """
    return RedirectResponse(f"/app?auth_error={quote(message)}", status_code=302)


def _exchange_code(code: str, request: Request) -> str:
    cid, secret = gitcode_client()
    with httpx.Client(**http_client_kwargs(15.0)) as client:
        resp = client.post(
            token_url(),
            params={"grant_type": "authorization_code", "code": code,
                    "client_id": cid, "redirect_uri": gitcode_redirect_uri(request)},
            data={"client_secret": secret},          # 文档要求 client_secret 走 form-data
        )
        if resp.status_code != 200:
            raise RuntimeError(f"换取 token 失败（{resp.status_code}）")
        token = (resp.json() or {}).get("access_token")
        if not token:
            raise RuntimeError("GitCode 没有返回 access_token")
        return token


def _fetch_profile(token: str) -> dict:
    with httpx.Client(**http_client_kwargs(15.0)) as client:
        resp = client.get(user_api(), headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            raise RuntimeError(f"获取 GitCode 用户资料失败（{resp.status_code}）")
        data = resp.json() or {}

    gid = data.get("id")
    if gid is None:
        raise RuntimeError("GitCode 用户资料里没有 id")
    return {
        "id": str(gid),                       # GitCode 的 id 是字符串
        "login": data.get("login") or "",
        "name": (data.get("name") or "").strip(),
        "avatar": data.get("avatar_url") or "",
    }


@router.get("/callback")
def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
             error: Optional[str] = None, error_description: Optional[str] = None,
             conn: sqlite3.Connection = Depends(get_db)):
    if not gitcode_enabled():
        return _fail("本站没有配置 GitCode 登录")
    if error:
        return _fail(error_description or f"GitCode 返回了错误：{error}")
    if not code or not state:
        return _fail("回调缺少 code 或 state")

    raw = request.cookies.get(OAUTH_COOKIE) or ""
    saved_state, _, target_id = raw.partition("|")
    purpose, _, target_id = target_id.partition("|")
    if not saved_state or not hmac.compare_digest(saved_state, state):
        return _fail("登录校验失败（state 不匹配），请重试")

    try:
        token = _exchange_code(code, request)
        profile = _fetch_profile(token)
    except (httpx.HTTPError, RuntimeError) as exc:
        return _fail(str(exc))
    except Exception:                              # noqa: BLE001 - 兜底成友好提示
        return _fail("与 GitCode 通信失败，请重试")

    gid = profile["id"]
    existing = conn.execute("SELECT * FROM users WHERE gitcode_id = ?", (gid,)).fetchone()

    if purpose == "bind":
        if not target_id.isdigit():
            return _fail("绑定请求已失效，请重新发起")
        me = conn.execute("SELECT * FROM users WHERE id = ?", (int(target_id),)).fetchone()
        if me is None:
            return _fail("账号不存在，请重新登录后再绑定")
        if existing and existing["id"] != me["id"]:
            return _fail(f"这个 GitCode 账号已经绑定了另一个账号（@{existing['username']}）")
        conn.execute(
            "UPDATE users SET gitcode_id = ?, avatar = COALESCE(NULLIF(?, ''), avatar) "
            "WHERE id = ?", (gid, profile["avatar"], me["id"]))
        conn.commit()
        resp = RedirectResponse("/app?bound=1#/settings", status_code=302)
        resp.delete_cookie(OAUTH_COOKIE, path="/")
        return resp

    # ── 登录：找到就登，没有就建 ──
    user = existing
    if user is None:
        base = _safe_username(profile["login"] or profile["name"] or "gitcode-user")
        username = _unique_username(conn, base)
        now = utcnow()
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, avatar, "
            " gitcode_id, created_at) VALUES (?,?,?,?,?,?)",
            (username, NO_PASSWORD,
             profile["name"] or profile["login"] or username,
             profile["avatar"], gid, now))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()

    token = create_session(conn, user["id"])
    resp = RedirectResponse("/app", status_code=302)
    set_session_cookie(request, resp, token)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    return resp


@router.post("/unbind")
def unbind(user=Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)):
    """解绑 GitCode。

    纯 GitCode 账号（没设过密码）不允许解绑，否则会把自己锁在门外。
    """
    if user["password_hash"] == NO_PASSWORD:
        raise HTTPException(
            status_code=400,
            detail="这个账号只能用 GitCode 登录，请先在「设置」里设置一个密码再解绑")
    conn.execute("UPDATE users SET gitcode_id = NULL WHERE id = ?", (user["id"],))
    conn.commit()
    return {"bound": False}
