"""对外公开页（匿名，不需要登录）。

设计要点：
- 只暴露 `links.public_show = 1` 的链接，逐条由本人（团队链接则是创建者/拥有者）勾选。
- 空间级别还有一道总开关：`users.public_enabled` / `teams.public_enabled`。
  关掉总开关，即使链接勾了公开，对外页也会整体消失。
- 页面按分组归类，前端拿到全量后自己做检索，所以这里不分页（规模是几百条）。
"""
from __future__ import annotations

import json
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_db
from ..services import parse_tags, valid_slug

router = APIRouter(prefix="/api/public", tags=["public"])

def _link_out(row: sqlite3.Row) -> dict:
    try:
        tags = json.loads(row["tags"] or "[]")
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"],
        "description": row["description"],
        "tags": tags if isinstance(tags, list) else [],
        "favicon": row["favicon"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        # 排序用：分组自身的顺序 + 链接在组内的顺序（跟 /app 里拖出来的一致）
        "group_position": row["gpos"],
        "position": row["position"] or 0,
        "updated_at": row["updated_at"],
    }


def _build(kind: str, name: str, rows, extra: dict | None = None) -> dict:
    """按分组归类；组内顺序、分组顺序都跟 /app 里拖出来的一致，未分组排最后。"""
    items = [_link_out(r) for r in rows]
    # 团队页要把「团队自有」和「成员放进来的」两个查询合起来，各自有序、拼起来会乱，
    # 所以这里统一再排一次：先按更新时间倒序垫底，再按分组/位置排（稳定排序）。
    items.sort(key=lambda it: (it["updated_at"] or "", it["id"]), reverse=True)
    items.sort(key=lambda it: (it["group_position"] is None,
                               it["group_position"] or 0,
                               it["group_name"] or "",
                               it["position"], it["id"]))

    buckets: dict = {}
    order: list = []
    for it in items:
        key = it["group_id"]
        if key not in buckets:
            buckets[key] = {"id": key, "name": it["group_name"] or "未分组", "links": []}
            order.append(key)
        buckets[key]["links"].append(it)

    groups = [buckets[k] for k in order if k is not None]
    ungrouped = buckets.get(None)
    if ungrouped:
        groups.append(ungrouped)

    tags: list[str] = []
    for it in items:
        for t in it["tags"]:
            if t not in tags:
                tags.append(t)

    payload = {
        "kind": kind,
        "name": name,
        "total": len(items),
        "groups": groups,
        "tags": sorted(tags),
    }
    if extra:
        payload.update(extra)
    return payload


@router.get("/u/{username}")
def public_personal(username: str, conn: sqlite3.Connection = Depends(get_db)):
    # 先按自定义地址找，再退回用户名 —— 这样改过地址之后，
    # 之前分享出去的 /u/<用户名> 老链接依然打得开。
    u = conn.execute("SELECT * FROM users WHERE public_slug = ?",
                     (username,)).fetchone()
    if not u:
        u = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                         (username,)).fetchone()
    if not u:
        raise HTTPException(status_code=404, detail="没有这个用户")
    if not u["public_enabled"]:
        raise HTTPException(status_code=404, detail="对方没有开启对外公开页")

    rows = conn.execute(
        "SELECT l.id, l.url, l.title, l.description, l.tags, l.favicon, "
        "       l.group_id, l.position, l.updated_at, "
        "       g.name AS group_name, g.position AS gpos "
        "FROM links l LEFT JOIN groups g ON g.id = l.group_id "
        "WHERE l.owner_user_id = ? AND l.team_id IS NULL AND l.public_show = 1",
        (u["id"],)).fetchall()

    # slug 给的是这个页面当前的规范地址（自定义过就是自定义的，否则是用户名），
    # 和团队公开页返回 slug 对称。
    return _build("personal", u["display_name"] or u["username"], rows,
                  {"username": u["username"],
                   "slug": u["public_slug"] or u["username"]})


@router.get("/t/{slug}")
def public_team(slug: str, conn: sqlite3.Connection = Depends(get_db)):
    team = conn.execute("SELECT * FROM teams WHERE public_slug = ?", (slug,)).fetchone()
    if not team:
        # 没设自定义地址时，规范地址是 team-<id>
        m = re.fullmatch(r"team-(\d+)", slug)
        if m:
            team = conn.execute("SELECT * FROM teams WHERE id = ?",
                                (int(m.group(1)),)).fetchone()
    if not team:
        raise HTTPException(status_code=404, detail="没有这个公开页")
    if not team["public_enabled"]:
        raise HTTPException(status_code=404, detail="该团队没有开启对外公开页")

    tid = team["id"]
    owner = conn.execute("SELECT display_name, username FROM users WHERE id = ?",
                         (team["owner_id"],)).fetchone()

    # 团队自有的公开链接 + 成员共享进团队空间、且本人勾了公开的个人链接
    team_rows = conn.execute(
        "SELECT l.id, l.url, l.title, l.description, l.tags, l.favicon, "
        "       l.group_id, l.position, l.updated_at, "
        "       g.name AS group_name, g.position AS gpos "
        "FROM links l LEFT JOIN groups g ON g.id = l.group_id "
        "WHERE l.team_id = ? AND l.public_show = 1",
        (tid,)).fetchall()
    shared_rows = conn.execute(
        "SELECT l.id, l.url, l.title, l.description, l.tags, l.favicon, "
        "       s.team_group_id AS group_id, s.position, l.updated_at, "
        "       g.name AS group_name, g.position AS gpos "
        "FROM link_team_links s JOIN links l ON l.id = s.link_id "
        "LEFT JOIN groups g ON g.id = s.team_group_id "
        "WHERE s.team_id = ? AND s.in_space = 1 AND l.public_show = 1",
        (tid,)).fetchall()

    return _build("team", team["name"], list(team_rows) + list(shared_rows),
                  {"slug": team["public_slug"] or f"team-{tid}",
                   "team_id": tid,
                   "owner_name": (owner["display_name"] or owner["username"]) if owner else ""})


@router.get("/directory")
def directory(conn: sqlite3.Connection = Depends(get_db)):
    """首页用：所有已开启对外公开的空间，供访客挑一个进去看。

    刻意排除「开了总开关但一条公开链接都没有」的空间——列出来点进去是空页，没意义。
    """
    # 一次取出所有对外公开的链接，在 Python 里归组，避免 N+1 查询
    own = conn.execute(
        "SELECT id, team_id, owner_user_id, tags, updated_at FROM links "
        "WHERE public_show = 1").fetchall()
    shared = conn.execute(
        "SELECT s.team_id, l.id, l.tags, l.updated_at "
        "FROM link_team_links s JOIN links l ON l.id = s.link_id "
        "WHERE s.in_space = 1 AND l.public_show = 1").fetchall()

    def add(bucket, key, row):
        b = bucket.setdefault(key, {"count": 0, "tags": [], "updated": ""})
        b["count"] += 1
        for t in parse_tags(row["tags"]):
            if t not in b["tags"]:
                b["tags"].append(t)
        if (row["updated_at"] or "") > b["updated"]:
            b["updated"] = row["updated_at"] or ""

    team_stat: dict = {}
    for r in own:
        if r["team_id"] is not None:
            add(team_stat, r["team_id"], r)
    for r in shared:
        add(team_stat, r["team_id"], r)

    people_stat: dict = {}
    for r in own:
        if r["team_id"] is None:
            add(people_stat, r["owner_user_id"], r)

    teams = []
    for row in conn.execute(
            "SELECT t.id, t.name, t.public_slug, t.owner_id, "
            "       u.display_name AS owner_display, u.username AS owner_username "
            "FROM teams t JOIN users u ON u.id = t.owner_id "
            "WHERE t.public_enabled = 1 ORDER BY t.name").fetchall():
        st = team_stat.get(row["id"])
        if not st:
            continue
        slug = row["public_slug"] or "team-%d" % row["id"]
        teams.append({
            "kind": "team",
            "id": row["id"],
            "name": row["name"],
            "url": "/t/" + slug,
            "link_count": st["count"],
            "owner_name": row["owner_display"] or row["owner_username"],
            "tags": st["tags"][:4],
            "updated_at": st["updated"],
        })
    teams.sort(key=lambda x: (-x["link_count"], x["name"]))

    people = []
    for row in conn.execute(
            "SELECT id, username, display_name, public_slug FROM users "
            "WHERE public_enabled = 1 ORDER BY display_name, username").fetchall():
        st = people_stat.get(row["id"])
        if not st:
            continue
        people.append({
            "kind": "personal",
            "id": row["id"],
            "name": row["display_name"] or row["username"],
            "username": row["username"],
            "url": f"/u/{row['public_slug'] or row['username']}",
            "link_count": st["count"],
            "tags": st["tags"][:4],
            "updated_at": st["updated"],
        })
    people.sort(key=lambda x: (-x["link_count"], x["name"]))

    return {"teams": teams, "people": people,
            "total": len(teams) + len(people)}


@router.get("/check-slug")
def check_slug(slug: str = Query(...), conn: sqlite3.Connection = Depends(get_db)):
    """给设置界面用的可用性检查（不需要登录，也不泄露团队名）。"""
    if not valid_slug(slug):
        return {"valid": False, "available": False,
                "reason": "只能用小写字母、数字和连字符，长度 2-40"}
    taken = conn.execute(
        "SELECT 1 FROM teams WHERE public_slug = ?", (slug,)).fetchone()
    if re.fullmatch(r"team-\d+", slug):
        return {"valid": True, "available": False, "reason": "team-<数字> 是系统保留格式"}
    return {"valid": True, "available": not taken,
            "reason": "" if not taken else "这个地址已被占用"}
