"""Shared FastAPI dependencies and permission helpers."""
from __future__ import annotations

import datetime
import sqlite3
from typing import Optional

from fastapi import Depends, HTTPException, Request

from .config import base_url_from
from .db import get_db, utcnow
from .security import new_token

COOKIE_NAME = "ml_session"
SESSION_DAYS = 30


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    """开一个会话并返回 token（顺带清掉过期会话）。

    密码登录和 GitCode 登录都走这里，避免两处各写一遍过期时间。
    """
    now = utcnow()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    token = new_token()
    expires = (datetime.datetime.now(datetime.timezone.utc)
               + datetime.timedelta(days=SESSION_DAYS)).replace(microsecond=0).isoformat()
    conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) "
                 "VALUES (?,?,?,?)", (token, user_id, now, expires))
    conn.commit()
    return token


def set_session_cookie(request: Request, resp, token: str):
    """种会话 cookie。

    secure 只在站点确实是 https 时才加：
      · 本地开发是 http://127.0.0.1，加了 secure 浏览器根本不存这个 cookie，
        登录会表现为「明明成功了，下一个请求又是未登录」，很难查；
      · 部署到 HTTPS 后不加 secure，cookie 就会在用户不小心走到 http:// 时
        明文发出去（降级攻击可窃取会话）。
    判断走 base_url_from()：它优先读 MAGICLINK_BASE_URL，正好覆盖
    「nginx 终止 TLS、uvicorn 看到的是 http」这种反代场景。
    """
    secure = base_url_from(request).lower().startswith("https://")
    resp.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=secure, path="/")
    return resp


def lookup_session(conn: sqlite3.Connection, request: Request) -> Optional[sqlite3.Row]:
    """按会话 cookie 取用户，取不到返回 None（不抛异常）。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    row = conn.execute(
        "SELECT u.*, s.expires_at AS _expires_at, s.token AS _token "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ?", (token,)).fetchone()
    if row is None:
        return None
    if row["_expires_at"] < utcnow():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    return row


def get_current_user(request: Request,
                     conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    if not request.cookies.get(COOKIE_NAME):
        raise HTTPException(status_code=401, detail="未登录")
    row = lookup_session(conn, request)
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效或已过期，请重新登录")
    return row


def user_public(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "avatar": row["avatar"] or "",
    }


# ── 团队权限 ────────────────────────────────────────────────────────────────

def team_role(conn: sqlite3.Connection, team_id: int,
              user_id: int) -> Optional[str]:
    r = conn.execute(
        "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
        (team_id, user_id)).fetchone()
    return r["role"] if r else None


def require_team_member(conn: sqlite3.Connection, team_id: int,
                        user_id: int) -> str:
    role = team_role(conn, team_id, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    return role


# 注：团队权限判断（require_team_member / require_team_owner / get_team_or_404）
# 只在 routers/teams.py 里有一份实现（_require_member / _require_owner / _team_or_404）。
# 这里曾经也放了一份一模一样的拷贝，但全项目没人调用——两份重复的权限判断
# 迟早会各自漂移，删掉留一份。
