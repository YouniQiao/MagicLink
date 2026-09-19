"""注册 / 登录 / 登出."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db import get_db, utcnow
from ..deps import (COOKIE_NAME, create_session, get_current_user,
                    set_session_cookie, user_public)
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=64)


class LoginIn(BaseModel):
    username: str
    password: str


def _start_session(conn: sqlite3.Connection, request: Request, response: Response,
                   user_id: int) -> None:
    set_session_cookie(request, response, create_session(conn, user_id))


@router.post("/register")
def register(payload: RegisterIn, request: Request, response: Response,
             conn: sqlite3.Connection = Depends(get_db)):
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")

    exists = conn.execute("SELECT 1 FROM users WHERE username = ?",
                          (username,)).fetchone()
    if exists:
        raise HTTPException(status_code=409, detail="用户名已被占用")

    cur = conn.execute(
        "INSERT INTO users (username, password_hash, display_name, avatar, created_at) "
        "VALUES (?,?,?,?,?)",
        (username, hash_password(payload.password),
         payload.display_name.strip() or username, "", utcnow()))
    user_id = cur.lastrowid
    conn.commit()

    _start_session(conn, request, response, user_id)
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"user": user_public(row)}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response,
          conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM users WHERE username = ?",
                       (payload.username.strip(),)).fetchone()
    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码不正确")

    _start_session(conn, request, response, row["id"])
    return {"user": user_public(row)}


@router.post("/logout")
def logout(response: Response, request_ctx=Depends(get_current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    token = request_ctx["_token"]
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
