"""抓取链接的标题 / 描述 / 图标（带超时和失败降级）."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import http_client_kwargs

router = APIRouter(prefix="/api/meta", tags=["meta"])

_TIMEOUT = 6.0
_MAX_BYTES = 512 * 1024
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class FetchIn(BaseModel):
    url: str


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="只支持 http/https 链接")
    if not p.netloc:
        raise HTTPException(status_code=400, detail="URL 不合法")
    return raw


def _assert_public_host(host: str) -> None:
    """基础 SSRF 防护：拒绝本机 / 内网地址。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="域名解析失败")

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="不支持内网地址")


def _client_kwargs() -> dict:
    """沿用统一的 httpx 设置（见 app/config.py 的说明）。"""
    return http_client_kwargs(_TIMEOUT)


def _clean_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title[:200]


def _meta_description(html: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()[:300]
    return ""


def _favicon(html: str, base_url: str) -> str:
    patterns = [
        r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]+href=["\'](.*?)["\']',
        r'<link[^>]+href=["\'](.*?)["\'][^>]+rel=["\'][^"\']*icon[^"\']*["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            href = m.group(1).strip()
            if href and not href.startswith("data:"):
                return urljoin(base_url, href)[:500]
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}/favicon.ico"


@router.post("/fetch")
def fetch_meta(payload: FetchIn):
    url = normalize_url(payload.url)
    p = urlparse(url)
    _assert_public_host(p.hostname or "")

    result = {"url": url, "title": "", "description": "",
              "favicon": f"{p.scheme}://{p.netloc}/favicon.ico", "ok": False}
    try:
        with httpx.Client(**_client_kwargs()) as client:
            resp = client.get(url)
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype.lower():
                result["ok"] = False
                result["error"] = f"目标不是网页（{ctype or '未知类型'}）"
                return result

            html = resp.text[:_MAX_BYTES]
            result["title"] = _clean_title(html)
            result["description"] = _meta_description(html)
            result["favicon"] = _favicon(html, str(resp.url))
            result["ok"] = bool(result["title"])
            return result
    except httpx.HTTPError as exc:
        result["error"] = f"请求失败：{type(exc).__name__}"
        return result
    except Exception as exc:  # noqa: BLE001 - 降级为手填
        result["error"] = f"抓取失败：{type(exc).__name__}"
        return result
