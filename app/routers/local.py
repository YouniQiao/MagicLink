"""个人空间：分组、链接、以及把链接共享给团队."""
from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_db, utcnow
from ..deps import get_current_user, team_role
from ..services import (dump_tags, get_group, get_link, get_shares,
                        link_tags_all, next_group_position, next_link_position,
                        next_team_link_position, query_links, serialize_link)

router = APIRouter(prefix="/api/local", tags=["local"])

PERSONAL_SCOPE = "l.team_id IS NULL AND l.owner_user_id = ?"


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    position: int = 0


class GroupPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    position: Optional[int] = None


class LinkIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = []
    favicon: str = Field(default="", max_length=500)
    group_id: Optional[int] = None
    public_show: bool = False


class LinkPatch(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2048)
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[list[str]] = None
    favicon: Optional[str] = Field(default=None, max_length=500)
    group_id: Optional[int] = None
    clear_group: bool = False
    public_show: Optional[bool] = None


class ShareIn(BaseModel):
    in_space: bool = False
    team_group_id: Optional[int] = None


class ReorderIn(BaseModel):
    """拖拽排序：items 是这一组在界面上的新顺序。"""
    items: list[int]


class LinkReorderIn(ReorderIn):
    group_id: Optional[int] = None


# ── 分组 ────────────────────────────────────────────────────────────────────

@router.get("/groups")
def list_groups(user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT g.*, (SELECT COUNT(*) FROM links l "
        "             WHERE l.group_id = g.id AND l.team_id IS NULL) AS link_count "
        "FROM groups g WHERE g.scope = 'personal' AND g.owner_user_id = ? "
        "ORDER BY g.position, g.id", (user["id"],)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/groups")
def create_group(payload: GroupIn, user=Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    # 不传 position 就排到最后（拖拽排序之后，新分组不该插在别人的位置上）
    pos = payload.position or next_group_position(
        conn, scope="personal", owner_user_id=user["id"])
    cur = conn.execute(
        "INSERT INTO groups (scope, owner_user_id, team_id, name, position, created_at) "
        "VALUES ('personal', ?, NULL, ?, ?, ?)",
        (user["id"], payload.name.strip(), pos, utcnow()))
    conn.commit()
    row = get_group(conn, cur.lastrowid)
    return dict(row)


@router.post("/groups/reorder")
def reorder_groups(payload: ReorderIn, user=Depends(get_current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    """按传进来的顺序重排个人分组。只认自己的分组，其余的一律忽略。"""
    moved = 0
    for idx, gid in enumerate(payload.items):
        row = get_group(conn, gid)
        if row is None or row["scope"] != "personal" or row["owner_user_id"] != user["id"]:
            continue
        conn.execute("UPDATE groups SET position = ? WHERE id = ?", (idx, gid))
        moved += 1
    conn.commit()
    return {"ok": True, "moved": moved}


@router.patch("/groups/{group_id}")
def update_group(group_id: int, payload: GroupPatch, user=Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    row = get_group(conn, group_id)
    if row is None or row["scope"] != "personal" or row["owner_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="分组不存在")

    fields, values = [], []
    if payload.name is not None:
        fields.append("name = ?")
        values.append(payload.name.strip())
    if payload.position is not None:
        fields.append("position = ?")
        values.append(payload.position)
    if fields:
        values.append(group_id)
        conn.execute(f"UPDATE groups SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return dict(get_group(conn, group_id))


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, user=Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    row = get_group(conn, group_id)
    if row is None or row["scope"] != "personal" or row["owner_user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="分组不存在")
    # 组内链接变为未分组（group_id 通过 FK ON DELETE SET NULL 处理）
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    return {"ok": True}


# ── 链接 ────────────────────────────────────────────────────────────────────

@router.get("/links")
def list_links(q: str = "", tag: str = "",
               group_id: Optional[int] = None, ungrouped: bool = False,
               page: int = 1, page_size: int = Query(default=100, le=500),
               user=Depends(get_current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    where = PERSONAL_SCOPE
    result = query_links(conn, where, [user["id"]], q=q, tag=tag,
                         group_id=group_id, ungrouped=ungrouped,
                         page=page, page_size=page_size)
    for item in result["items"]:
        item["shares"] = get_shares(conn, item["id"])
    result["tags"] = link_tags_all(conn, where, [user["id"]])
    return result


def _validate_personal_group(conn: sqlite3.Connection, group_id, user_id) -> None:
    if group_id is None:
        return
    g = get_group(conn, group_id)
    if g is None or g["scope"] != "personal" or g["owner_user_id"] != user_id:
        raise HTTPException(status_code=400, detail="分组不存在")


@router.post("/links")
def create_link(payload: LinkIn, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _validate_personal_group(conn, payload.group_id, user["id"])
    now = utcnow()
    pos = next_link_position(conn, owner_user_id=user["id"],
                             group_id=payload.group_id)
    cur = conn.execute(
        "INSERT INTO links (owner_user_id, team_id, group_id, url, title, description,"
        " tags, favicon, public_show, position, created_at, updated_at) "
        "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], payload.group_id, payload.url.strip(),
         payload.title.strip(), payload.description.strip(),
         dump_tags(payload.tags), payload.favicon.strip(),
         1 if payload.public_show else 0, pos, now, now))
    conn.commit()
    row = get_link(conn, cur.lastrowid)
    out = serialize_link(row)
    out["shares"] = []
    return out


def _own_personal_link(conn: sqlite3.Connection, link_id: int, user_id: int):
    row = get_link(conn, link_id)
    if row is None or row["team_id"] is not None or row["owner_user_id"] != user_id:
        raise HTTPException(status_code=404, detail="链接不存在")
    return row


@router.patch("/links/{link_id}")
def update_link(link_id: int, payload: LinkPatch, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    before = _own_personal_link(conn, link_id, user["id"])

    fields, values = [], []
    if payload.url is not None:
        fields.append("url = ?"); values.append(payload.url.strip())
    if payload.title is not None:
        fields.append("title = ?"); values.append(payload.title.strip())
    if payload.description is not None:
        fields.append("description = ?"); values.append(payload.description.strip())
    if payload.tags is not None:
        fields.append("tags = ?"); values.append(dump_tags(payload.tags))
    if payload.favicon is not None:
        fields.append("favicon = ?"); values.append(payload.favicon.strip())
    target_group = before["group_id"]
    if payload.clear_group:
        fields.append("group_id = NULL")
        target_group = None
    elif payload.group_id is not None:
        _validate_personal_group(conn, payload.group_id, user["id"])
        fields.append("group_id = ?"); values.append(payload.group_id)
        target_group = payload.group_id
    # 换分组了就排到新分组最后——拖拽攒下来的顺序只在原分组里有意义
    if target_group != before["group_id"]:
        fields.append("position = ?")
        values.append(next_link_position(conn, owner_user_id=user["id"],
                                         group_id=target_group))
    if payload.public_show is not None:
        fields.append("public_show = ?"); values.append(1 if payload.public_show else 0)

    if fields:
        fields.append("updated_at = ?"); values.append(utcnow())
        values.append(link_id)
        conn.execute(f"UPDATE links SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    out = serialize_link(get_link(conn, link_id))
    out["shares"] = get_shares(conn, link_id)
    return out


@router.delete("/links/{link_id}")
def delete_link(link_id: int, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _own_personal_link(conn, link_id, user["id"])
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()
    return {"ok": True}


@router.post("/links/reorder")
def reorder_links(payload: LinkReorderIn, user=Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """按下发顺序重排某个分组里的链接（拖拽排序）。

    只认属于自己、并且确实在这个分组里的链接——前端只发一组的 id 列表，
    后端仍然逐个校验，避免拖拽接口变成「批量改任意链接」的后门。
    """
    moved = 0
    for idx, lid in enumerate(payload.items):
        row = get_link(conn, lid)
        if row is None or row["team_id"] is not None or row["owner_user_id"] != user["id"]:
            continue
        if row["group_id"] != payload.group_id:
            continue
        conn.execute("UPDATE links SET position = ? WHERE id = ?", (idx, lid))
        moved += 1
    conn.commit()
    return {"ok": True, "moved": moved}


# ── 共享给团队（引用同一份；两个独立开关，按团队存）────────────────────────

@router.get("/links/{link_id}/shares")
def list_shares(link_id: int, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _own_personal_link(conn, link_id, user["id"])
    return {"items": get_shares(conn, link_id)}


@router.put("/links/{link_id}/shares/{team_id}")
def set_share(link_id: int, team_id: int, payload: ShareIn,
              user=Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    """把这条个人链接放进 / 移出某个团队的链接列表。"""
    _own_personal_link(conn, link_id, user["id"])
    if team_role(conn, team_id, user["id"]) is None:
        raise HTTPException(status_code=403, detail="你不是该团队成员")

    if payload.team_group_id is not None:
        g = get_group(conn, payload.team_group_id)
        if g is None or g["scope"] != "team" or g["team_id"] != team_id:
            raise HTTPException(status_code=400, detail="团队分组不存在")

    if not payload.in_space:
        # 不放进团队列表 = 没有这条共享记录
        conn.execute("DELETE FROM link_team_links WHERE link_id = ? AND team_id = ?",
                     (link_id, team_id))
        conn.commit()
        return {"items": get_shares(conn, link_id)}

    # in_profile 是已废弃列（「队友进我主页可见」那个功能已下线），
    # 这里跟着 in_space 一起写，只是让旧列不至于和事实矛盾。
    # position：换到别的团队分组时排到该分组最后；原来的位置留着不动（同一分组重放）。
    prev = conn.execute(
        "SELECT team_group_id, position FROM link_team_links "
        "WHERE link_id = ? AND team_id = ?", (link_id, team_id)).fetchone()
    if prev is None or prev["team_group_id"] != payload.team_group_id:
        pos = next_team_link_position(conn, team_id=team_id,
                                      group_id=payload.team_group_id)
    else:
        pos = prev["position"]

    conn.execute(
        "INSERT INTO link_team_links (link_id, team_id, in_space, in_profile,"
        " team_group_id, position, created_by, created_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(link_id, team_id) DO UPDATE SET "
        "  in_space = excluded.in_space, "
        "  in_profile = excluded.in_profile, "
        "  team_group_id = excluded.team_group_id, "
        "  position = excluded.position",
        (link_id, team_id, 1, 1,
         payload.team_group_id, pos,
         user["id"], utcnow()))
    conn.commit()
    return {"items": get_shares(conn, link_id)}


@router.delete("/links/{link_id}/shares/{team_id}")
def remove_share(link_id: int, team_id: int, user=Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _own_personal_link(conn, link_id, user["id"])
    conn.execute("DELETE FROM link_team_links WHERE link_id = ? AND team_id = ?",
                 (link_id, team_id))
    conn.commit()
    return {"items": get_shares(conn, link_id)}
