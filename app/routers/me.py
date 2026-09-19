"""当前用户信息 / 改昵称 / 改密码."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import gitcode_enabled
from ..db import get_db
from ..deps import get_current_user, user_public
from ..security import NO_PASSWORD, hash_password, verify_password

router = APIRouter(prefix="/api/me", tags=["me"])


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    avatar: str | None = Field(default=None, max_length=512)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


@router.get("")
def me(user=Depends(get_current_user), conn: sqlite3.Connection = Depends(get_db)):
    teams = conn.execute(
        "SELECT t.id, t.name, t.owner_id, m.role, "
        "  (SELECT COUNT(*) FROM team_members x WHERE x.team_id = t.id) AS member_count, "
        "  (SELECT COUNT(*) FROM links l WHERE l.team_id = t.id) AS link_count, "
        "  (SELECT COUNT(*) FROM link_team_links s "
        "     WHERE s.team_id = t.id AND s.in_space = 1) AS shared_count "
        "FROM team_members m JOIN teams t ON t.id = m.team_id "
        "WHERE m.user_id = ? ORDER BY t.id", (user["id"],)).fetchall()
    return {
        # 说明：SPA 只把 user 对象留在内存里，所以「服务端能力」这类标志
        # （比如 GitCode 是否已配置）也必须挂在 user 下，否则前端拿不到。
        "user": {**user_public(user),
                 "public_enabled": bool(user["public_enabled"]),
                 "public_url": f"/u/{user['username']}" if user["public_enabled"] else None,
                 "gitcode_bound": bool(user["gitcode_id"]),
                 "gitcode_login_enabled": gitcode_enabled(),
                 "has_password": user["password_hash"] != NO_PASSWORD},
        "teams": [dict(r) for r in teams],
    }


class PublicIn(BaseModel):
    enabled: bool


@router.post("/public")
def set_my_public(payload: PublicIn, user=Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """开启/关闭我自己的对外公开页（地址就是 /u/<用户名>）。"""
    conn.execute("UPDATE users SET public_enabled = ? WHERE id = ?",
                 (1 if payload.enabled else 0, user["id"]))
    conn.commit()
    row = conn.execute("SELECT username, public_enabled FROM users WHERE id = ?",
                       (user["id"],)).fetchone()
    return {
        "public_enabled": bool(row["public_enabled"]),
        "public_url": f"/u/{row['username']}" if row["public_enabled"] else None,
    }


@router.patch("")
def update_profile(payload: ProfileIn, user=Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    fields, values = [], []
    if payload.display_name is not None:
        fields.append("display_name = ?")
        values.append(payload.display_name.strip())
    if payload.avatar is not None:
        fields.append("avatar = ?")
        values.append(payload.avatar.strip())
    if not fields:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    values.append(user["id"])
    conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return {"user": user_public(row)}


@router.post("/password")
def change_password(payload: PasswordIn, user=Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    # 纯 GitCode 账号没设过密码：当前会话已经证明过身份，允许直接设置新密码
    has_password = user["password_hash"] != NO_PASSWORD
    if has_password and not verify_password(payload.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (hash_password(payload.new_password), user["id"]))
    # 改密后让其它会话失效，只保留当前这一个
    conn.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?",
                 (user["id"], user["_token"]))
    conn.commit()
    return {"ok": True}
