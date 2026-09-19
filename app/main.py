"""MagicLink — 链接管理（个人空间 / 团队空间）."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import auth, gitcode, local, me, meta, public, teams

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时建表 / 补列。

    用 lifespan 而不是 @app.on_event("startup")——后者在 FastAPI 0.141 已废弃，
    每次启动都打一条 DeprecationWarning。
    """
    init_db()
    yield


app = FastAPI(title="MagicLink", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def cache_headers(request, call_next):
    """静态资源 no-cache，接口 no-store。

    - 静态资源加 no-cache（= 每次带 ETag 重新验证，命中就是 304）：不这么做的话，
      改了 js/css 之后浏览器会继续用旧文件，页面行为对不上代码，排查起来非常费劲。
      no-cache 不是「不缓存」，只是「用之前先问一下」。
    - 接口加 no-store：API 响应本来就该每次重新取。之前漏了这一步，浏览器按启发式
      规则缓存了 /api/me，导致前端一直拿着旧数据（改了字段也看不到变化）。
    """
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    else:
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": "MagicLink"}


app.include_router(auth.router)
app.include_router(gitcode.router)
app.include_router(me.router)
app.include_router(local.router)
app.include_router(teams.router)
app.include_router(meta.router)
app.include_router(public.router)


# ── 对外公开页 ──────────────────────────────────────────────────────────────
# 独立的静态页（不加载主应用、不需要登录），地址可读：
#   首页   /            公开空间目录（列出所有开启公开的团队/个人空间）
#   个人页 /u/<用户名>   团队页 /t/<团队地址>
# 页面本身只是壳，数据由 /api/public/* 提供；未开启时接口返回 404，
# 前端会渲染「这个公开页不存在或已关闭」，避免用页面标题泄露信息。

_HOME_PAGE = WEB_DIR / "home.html"
_APP_PAGE = WEB_DIR / "index.html"
_PUBLIC_PAGE = WEB_DIR / "public.html"
_IDENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    """首页是公开空间目录，不是登录界面。"""
    return FileResponse(_HOME_PAGE)


@app.get("/app", include_in_schema=False)
def app_page() -> FileResponse:
    """登录与空间管理界面（原首页位置）。"""
    return FileResponse(_APP_PAGE)


@app.get("/u/{username}", include_in_schema=False)
def public_page_user(username: str) -> FileResponse:
    if not _IDENT.match(username):
        raise HTTPException(status_code=404)
    return FileResponse(_PUBLIC_PAGE)


@app.get("/t/{slug}", include_in_schema=False)
def public_page_team(slug: str) -> FileResponse:
    if not _IDENT.match(slug):
        raise HTTPException(status_code=404)
    return FileResponse(_PUBLIC_PAGE)


# 前端静态文件挂到最后，避免遮蔽上面的 API 路由
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
