"""团队：创建/加入、成员、团队分组与链接、共享进来的个人链接、复制到个人空间."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_db, utcnow
from ..deps import get_current_user, team_role
from ..security import new_invite_code
from ..services import (LINK_ORDER_BY, LINK_SELECT, dump_tags, get_group, get_link,
                        next_group_position, next_team_link_position,
                        parse_tags,
                        serialize_link, sort_links)
from .local import LinkIn, LinkPatch, ReorderIn
from .public import valid_slug

router = APIRouter(prefix="/api/teams", tags=["teams"])


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class TeamPatch(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class JoinIn(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)


class TeamGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    position: int = 0


class TeamGroupPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=64)
    position: Optional[int] = None


class CopyIn(BaseModel):
    group_id: Optional[int] = None


class TeamOrderItem(BaseModel):
    """团队链接有两种来源，排序时得说清是哪种。"""
    kind: str          # 'team'（团队自有）| 'shared'（成员放进来的个人链接）
    id: int


class TeamLinkReorderIn(BaseModel):
    group_id: Optional[int] = None
    items: list[TeamOrderItem]


class PublicIn(BaseModel):
    enabled: bool
    slug: Optional[str] = Field(default=None, max_length=40)


def _require_member(conn, team_id: int, user_id: int) -> str:
    role = team_role(conn, team_id, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="你不是该团队成员")
    return role


def _require_owner(conn, team_id: int, user_id: int) -> str:
    role = _require_member(conn, team_id, user_id)
    if role != "owner":
        raise HTTPException(status_code=403, detail="只有团队拥有者可以执行此操作")
    return role


def _fresh_invite_code(conn: sqlite3.Connection) -> str:
    """生成一个未被占用的邀请码。

    10 位 × 32 个字符表，撞车概率约等于零；但 invite_code 上有 UNIQUE 约束，
    真撞上就是一次 500。留一个「无法复现的崩溃点」不值得，查一下再发就是了。
    """
    for _ in range(5):
        code = new_invite_code()
        if conn.execute("SELECT 1 FROM teams WHERE invite_code = ?",
                        (code,)).fetchone() is None:
            return code
    raise HTTPException(status_code=500, detail="生成邀请码失败，请重试")


def _team_or_404(conn, team_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return row


# ── 团队本体 ────────────────────────────────────────────────────────────────

@router.get("")
def my_teams(user=Depends(get_current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT t.id, t.name, t.owner_id, m.role, t.created_at, "
        "  (SELECT COUNT(*) FROM team_members x WHERE x.team_id = t.id) AS member_count, "
        "  (SELECT COUNT(*) FROM links l WHERE l.team_id = t.id) AS link_count "
        "FROM team_members m JOIN teams t ON t.id = m.team_id "
        "WHERE m.user_id = ? ORDER BY t.id", (user["id"],)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("")
def create_team(payload: TeamIn, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO teams (name, owner_id, invite_code, created_at) VALUES (?,?,?,?)",
        (payload.name.strip(), user["id"], _fresh_invite_code(conn), now))
    team_id = cur.lastrowid
    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (team_id, user["id"], "owner", now))
    conn.commit()
    row = _team_or_404(conn, team_id)
    return {"id": row["id"], "name": row["name"], "role": "owner",
            "invite_code": row["invite_code"]}


@router.post("/join")
def join_team(payload: JoinIn, user=Depends(get_current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    code = payload.invite_code.strip().upper()
    team = conn.execute("SELECT * FROM teams WHERE UPPER(invite_code) = ?",
                        (code,)).fetchone()
    if team is None:
        raise HTTPException(status_code=404, detail="邀请码无效")

    # 已经在队里就当成功返回，别报错（同一个人反复点「加入」不该弹错）。
    # 但要把「本来就在」和「这次加进去了」区分开——否则前端只能瞎猜，
    # 于是对着一个早就在的团队说「已加入」。
    existing = team_role(conn, team["id"], user["id"])
    if existing:
        return {"id": team["id"], "name": team["name"], "role": existing,
                "already_member": True}

    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (team["id"], user["id"], "member", utcnow()))
    conn.commit()
    return {"id": team["id"], "name": team["name"], "role": "member",
            "already_member": False}


@router.get("/{team_id}")
def team_detail(team_id: int, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    role = _require_member(conn, team_id, user["id"])
    team = _team_or_404(conn, team_id)
    counts = conn.execute(
        "SELECT (SELECT COUNT(*) FROM team_members WHERE team_id = ?) AS member_count, "
        "       (SELECT COUNT(*) FROM links WHERE team_id = ?) AS link_count, "
        "       (SELECT COUNT(*) FROM link_team_links WHERE team_id = ? AND in_space = 1)"
        "         AS shared_count", (team_id, team_id, team_id)).fetchone()
    return {
        "id": team["id"], "name": team["name"], "owner_id": team["owner_id"],
        "my_role": role,
        "invite_code": team["invite_code"] if role == "owner" else None,
        "member_count": counts["member_count"],
        "link_count": counts["link_count"],
        "shared_count": counts["shared_count"],
        "public_enabled": bool(team["public_enabled"]),
        "public_slug": team["public_slug"] if role == "owner" else None,
        "public_url": f"/t/{team['public_slug'] or f'team-{team_id}'}"
                      if team["public_enabled"] else None,
    }


@router.patch("/{team_id}")
def update_team(team_id: int, payload: TeamPatch, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _require_owner(conn, team_id, user["id"])
    conn.execute("UPDATE teams SET name = ? WHERE id = ?",
                 (payload.name.strip(), team_id))
    conn.commit()
    return {"ok": True}


@router.post("/{team_id}/invite/regenerate")
def regenerate_invite(team_id: int, user=Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    _require_owner(conn, team_id, user["id"])
    code = _fresh_invite_code(conn)
    conn.execute("UPDATE teams SET invite_code = ? WHERE id = ?", (code, team_id))
    conn.commit()
    return {"invite_code": code}


@router.post("/{team_id}/public")
def set_team_public(team_id: int, payload: PublicIn, user=Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    """开启/关闭团队的对外公开页，并设置可读地址（拥有者）。"""
    _require_owner(conn, team_id, user["id"])
    slug = (payload.slug or "").strip().lower() or None
    if slug is not None:
        if not valid_slug(slug):
            raise HTTPException(
                status_code=400,
                detail="地址只能用小写字母、数字和连字符，长度 2-40，且不能以连字符开头/结尾")
        if re.fullmatch(r"team-\d+", slug):
            raise HTTPException(status_code=400, detail="team-<数字> 是系统保留格式")
        clash = conn.execute(
            "SELECT 1 FROM teams WHERE public_slug = ? AND id <> ?", (slug, team_id)).fetchone()
        if clash:
            raise HTTPException(status_code=409, detail="这个地址已被其他团队占用")

    conn.execute("UPDATE teams SET public_enabled = ?, public_slug = ? WHERE id = ?",
                 (1 if payload.enabled else 0, slug, team_id))
    conn.commit()
    row = conn.execute("SELECT public_enabled, public_slug FROM teams WHERE id = ?",
                       (team_id,)).fetchone()
    return {
        "public_enabled": bool(row["public_enabled"]),
        "public_slug": row["public_slug"],
        "public_url": f"/t/{row['public_slug'] or f'team-{team_id}'}"
                      if row["public_enabled"] else None,
    }


@router.delete("/{team_id}")
def delete_team(team_id: int, user=Depends(get_current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _require_owner(conn, team_id, user["id"])
    conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()
    return {"ok": True}


# ── 成员 ────────────────────────────────────────────────────────────────────

@router.get("/{team_id}/members")
def list_members(team_id: int, user=Depends(get_current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    rows = conn.execute(
        "SELECT u.id, u.username, u.display_name, u.avatar, m.role, m.joined_at, "
        "  (SELECT COUNT(*) FROM links l "
        "   WHERE l.team_id = m.team_id AND l.owner_user_id = u.id) "
        "   AS contributed_count "
        "FROM team_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.team_id = ? ORDER BY m.role = 'owner' DESC, u.id", (team_id,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.delete("/{team_id}/members/{user_id}")
def remove_member(team_id: int, user_id: int, user=Depends(get_current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    my_role = _require_member(conn, team_id, user["id"])
    team = _team_or_404(conn, team_id)

    if user_id == user["id"]:
        if my_role == "owner":
            raise HTTPException(status_code=400,
                                detail="拥有者不能退出团队，请先删除团队或转让")
    elif my_role != "owner":
        raise HTTPException(status_code=403, detail="只有团队拥有者可以移除成员")

    if user_id == team["owner_id"]:
        raise HTTPException(status_code=400, detail="不能移除团队拥有者")

    conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
                 (team_id, user_id))
    conn.commit()
    return {"ok": True}


# ── 团队分组 ────────────────────────────────────────────────────────────────

@router.get("/{team_id}/groups")
def list_team_groups(team_id: int, user=Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    rows = conn.execute(
        "SELECT g.*, "
        " (SELECT COUNT(*) FROM links l WHERE l.group_id = g.id AND l.team_id = g.team_id)"
        "   + (SELECT COUNT(*) FROM link_team_links ltl "
        "      WHERE ltl.team_group_id = g.id AND ltl.in_space = 1) AS link_count "
        "FROM groups g WHERE g.scope = 'team' AND g.team_id = ? "
        "ORDER BY g.position, g.id", (team_id,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/{team_id}/groups")
def create_team_group(team_id: int, payload: TeamGroupIn,
                      user=Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    pos = payload.position or next_group_position(
        conn, scope="team", team_id=team_id)
    cur = conn.execute(
        "INSERT INTO groups (scope, owner_user_id, team_id, name, position, created_at) "
        "VALUES ('team', NULL, ?, ?, ?, ?)",
        (team_id, payload.name.strip(), pos, utcnow()))
    conn.commit()
    return dict(get_group(conn, cur.lastrowid))


@router.post("/{team_id}/groups/reorder")
def reorder_team_groups(team_id: int, payload: ReorderIn,
                        user=Depends(get_current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    """按拖拽后的顺序重排团队分组。任何成员都能调——团队分组是共用的。"""
    _require_member(conn, team_id, user["id"])
    moved = 0
    for idx, gid in enumerate(payload.items):
        row = get_group(conn, gid)
        if row is None or row["scope"] != "team" or row["team_id"] != team_id:
            continue
        conn.execute("UPDATE groups SET position = ? WHERE id = ?", (idx, gid))
        moved += 1
    conn.commit()
    return {"ok": True, "moved": moved}


@router.patch("/{team_id}/groups/{group_id}")
def update_team_group(team_id: int, group_id: int, payload: TeamGroupPatch,
                      user=Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    row = get_group(conn, group_id)
    if row is None or row["scope"] != "team" or row["team_id"] != team_id:
        raise HTTPException(status_code=404, detail="分组不存在")

    fields, values = [], []
    if payload.name is not None:
        fields.append("name = ?"); values.append(payload.name.strip())
    if payload.position is not None:
        fields.append("position = ?"); values.append(payload.position)
    if fields:
        values.append(group_id)
        conn.execute(f"UPDATE groups SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return dict(get_group(conn, group_id))


@router.delete("/{team_id}/groups/{group_id}")
def delete_team_group(team_id: int, group_id: int,
                      user=Depends(get_current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    my_role = _require_member(conn, team_id, user["id"])
    row = get_group(conn, group_id)
    if row is None or row["scope"] != "team" or row["team_id"] != team_id:
        raise HTTPException(status_code=404, detail="分组不存在")
    if my_role != "owner":
        # 成员只有在分组内没有别人贡献的链接时才能删
        others = conn.execute(
            "SELECT COUNT(*) AS c FROM links l WHERE l.group_id = ? "
            "  AND l.team_id = ? AND l.owner_user_id != ?",
            (group_id, team_id, user["id"])).fetchone()["c"]
        if others:
            raise HTTPException(status_code=403,
                                detail="该分组内有其他成员贡献的链接，只有拥有者可以删除")
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    return {"ok": True}


# ── 团队链接（团队自己的 + 成员共享进来的）──────────────────────────────────

def _team_items(conn, team_id: int, user_id: int, *, q: str, tag: str,
                group_id: Optional[int], ungrouped: bool) -> list[dict]:
    q = (q or "").strip()
    tag = (tag or "").strip()

    def matches(row) -> bool:
        if q:
            hay = " ".join([str(row["title"] or ""), str(row["url"] or ""),
                            str(row["description"] or ""),
                            " ".join(parse_tags(row["tags"]))]).lower()
            if not all(part in hay for part in q.lower().split()):
                return False
        if tag and tag not in parse_tags(row["tags"]):
            return False
        return True

    items: list[dict] = []

    # 1) 团队自有链接
    team_rows = conn.execute(
        LINK_SELECT + "WHERE l.team_id = ? " +
        f"ORDER BY {LINK_ORDER_BY}", (team_id,)).fetchall()
    for r in team_rows:
        if group_id is not None and r["group_id"] != group_id:
            continue
        if ungrouped and r["group_id"] is not None:
            continue
        if not matches(r):
            continue
        d = serialize_link(r)
        d["kind"] = "team"
        d["owner_id"] = r["owner_user_id"]
        d["owner_name"] = ""
        d["can_edit"] = (r["owner_user_id"] == user_id)
        d["can_remove"] = d["can_edit"]
        items.append(d)

    # 2) 成员放进团队列表的个人链接（in_space = 1）
    #    position 取 ltl 的：同一条链接在自己那边的位置和在这里的位置是两套。
    shared_rows = conn.execute(
        "SELECT l.*, g.name AS group_name, g.position AS group_position, "
        "       ltl.team_group_id, ltl.position AS team_position, "
        "       u.username AS owner_username, u.display_name AS owner_display_name "
        "FROM link_team_links ltl "
        "JOIN links l ON l.id = ltl.link_id "
        "LEFT JOIN groups g ON g.id = ltl.team_group_id "
        "JOIN users u ON u.id = l.owner_user_id "
        "WHERE ltl.team_id = ? AND ltl.in_space = 1", (team_id,)).fetchall()
    for r in shared_rows:
        if group_id is not None and r["team_group_id"] != group_id:
            continue
        if ungrouped and r["team_group_id"] is not None:
            continue
        if not matches(r):
            continue
        d = serialize_link(r)
        d["group_id"] = r["team_group_id"]
        d["position"] = r["team_position"] or 0
        d["kind"] = "shared"
        d["owner_id"] = r["owner_user_id"]
        d["owner_name"] = r["owner_display_name"] or r["owner_username"]
        d["can_edit"] = (r["owner_user_id"] == user_id)   # 个人链接只有本人能改内容
        d["can_remove"] = d["can_edit"]
        items.append(d)

    # 两个来源各自有序，拼起来会乱；按统一的尺子（分组 position → 组内 position）再排一次
    sort_links(items)

    # 注意：这里**不**做「谁能删」的判定。权限和请求者角色有关，
    # 而本函数按用户无关的方式组装条目——角色放开的那部分统一在
    # list_team_links 里按 role 处理（曾经在这里无条件把 can_remove 设成 True，
    # 结果普通成员看到别人链接上也有删除按钮，点下去 403）。
    return items


@router.get("/{team_id}/links")
def list_team_links(team_id: int, q: str = "", tag: str = "",
                    group_id: Optional[int] = None, ungrouped: bool = False,
                    page: int = 1, page_size: int = Query(default=100, le=500),
                    user=Depends(get_current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    role = _require_member(conn, team_id, user["id"])
    items = _team_items(conn, team_id, user["id"], q=q, tag=tag,
                        group_id=group_id, ungrouped=ungrouped)

    # 拥有者对「团队自有链接」有完全权限：改内容、删都行（和 update/remove 接口一致）。
    # 但成员共享进来的个人链接例外——内容归本人，拥有者只能把它移出团队，
    # 改不了内容（改内容请让本人去自己的个人空间改）。
    if role == "owner":
        for d in items:
            d["can_remove"] = True
            if d["kind"] == "team":
                d["can_edit"] = True

    total = len(items)
    page = max(1, page)
    page_size = max(1, min(500, page_size))
    start = (page - 1) * page_size
    sliced = items[start:start + page_size]

    # 团队自有链接的创建人名字。按 users 查而不是按当前成员查：
    # 添加者可能已经退队，退队之后卡片上不该变成没人。
    creator_ids = {d["owner_id"] for d in sliced if d.get("owner_id")}
    name_map = {}
    if creator_ids:
        holes = ",".join("?" * len(creator_ids))
        name_map = {
            r["id"]: (r["display_name"] or r["username"])
            for r in conn.execute(
                f"SELECT id, username, display_name FROM users "
                f"WHERE id IN ({holes})", tuple(creator_ids)).fetchall()
        }
    for d in sliced:
        if d["kind"] == "team":
            d["owner_name"] = name_map.get(d["owner_id"], "")

    tags_all = sorted({t for d in items for t in d["tags"]})
    return {"items": sliced, "total": total, "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "tags": tags_all, "my_role": role}


@router.post("/{team_id}/links")
def create_team_link(team_id: int, payload: LinkIn,
                     user=Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    if payload.group_id is not None:
        g = get_group(conn, payload.group_id)
        if g is None or g["scope"] != "team" or g["team_id"] != team_id:
            raise HTTPException(status_code=400, detail="团队分组不存在")

    now = utcnow()
    pos = next_team_link_position(conn, team_id=team_id, group_id=payload.group_id)
    cur = conn.execute(
        "INSERT INTO links (owner_user_id, team_id, group_id, url, title, description,"
        " tags, favicon, public_show, position, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], team_id, payload.group_id, payload.url.strip(),
         payload.title.strip(), payload.description.strip(),
         dump_tags(payload.tags), payload.favicon.strip(),
         1 if payload.public_show else 0, pos, now, now))
    conn.commit()
    row = get_link(conn, cur.lastrowid)
    out = serialize_link(row)
    out["kind"] = "team"
    out["owner_id"] = user["id"]
    out["owner_name"] = user["display_name"] or user["username"]
    out["can_edit"] = out["can_remove"] = True
    return out


@router.post("/{team_id}/links/reorder")
def reorder_team_links(team_id: int, payload: TeamLinkReorderIn,
                       user=Depends(get_current_user),
                       conn: sqlite3.Connection = Depends(get_db)):
    """按拖拽后的顺序重排某个团队分组里的链接。

    团队链接有两种来源，共用一个顺序：团队自有的写 links.position，
    成员放进来的写 link_team_links.position——两边用同一串下标编号，
    列表按 position 合起来排就是用户看到的样子。
    """
    _require_member(conn, team_id, user["id"])
    moved = 0
    for idx, item in enumerate(payload.items):
        if item.kind == "team":
            row = get_link(conn, item.id)
            if row is None or row["team_id"] != team_id:
                continue
            if row["group_id"] != payload.group_id:
                continue
            conn.execute("UPDATE links SET position = ? WHERE id = ?", (idx, item.id))
        elif item.kind == "shared":
            row = conn.execute(
                "SELECT team_group_id FROM link_team_links "
                "WHERE link_id = ? AND team_id = ? AND in_space = 1",
                (item.id, team_id)).fetchone()
            if row is None or row["team_group_id"] != payload.group_id:
                continue
            conn.execute(
                "UPDATE link_team_links SET position = ? "
                "WHERE link_id = ? AND team_id = ?", (idx, item.id, team_id))
        else:
            continue
        moved += 1
    conn.commit()
    return {"ok": True, "moved": moved}


@router.patch("/{team_id}/links/{link_id}")
def update_team_link(team_id: int, link_id: int, payload: LinkPatch,
                     user=Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    role = _require_member(conn, team_id, user["id"])
    row = get_link(conn, link_id)
    if row is None or row["team_id"] != team_id:
        raise HTTPException(
            status_code=400,
            detail="这是成员共享的个人链接，内容请到该成员的「个人空间」修改")

    if row["owner_user_id"] != user["id"] and role != "owner":
        raise HTTPException(status_code=403, detail="不能修改其他成员贡献的链接")

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
    target_group = row["group_id"]
    if payload.clear_group:
        fields.append("group_id = NULL")
        target_group = None
    elif payload.group_id is not None:
        g = get_group(conn, payload.group_id)
        if g is None or g["scope"] != "team" or g["team_id"] != team_id:
            raise HTTPException(status_code=400, detail="团队分组不存在")
        fields.append("group_id = ?"); values.append(payload.group_id)
        target_group = payload.group_id
    # 换分组了就排到新分组最后（同 local.update_link）
    if target_group != row["group_id"]:
        fields.append("position = ?")
        values.append(next_team_link_position(conn, team_id=team_id,
                                              group_id=target_group))
    if payload.public_show is not None:
        fields.append("public_show = ?"); values.append(1 if payload.public_show else 0)

    if fields:
        fields.append("updated_at = ?"); values.append(utcnow())
        values.append(link_id)
        conn.execute(f"UPDATE links SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    out = serialize_link(get_link(conn, link_id))
    out["kind"] = "team"
    out["owner_id"] = row["owner_user_id"]
    owner = conn.execute("SELECT username, display_name FROM users WHERE id = ?",
                         (row["owner_user_id"],)).fetchone()
    out["owner_name"] = ((owner["display_name"] or owner["username"])
                         if owner else "")
    out["can_edit"] = out["can_remove"] = True
    return out


@router.delete("/{team_id}/links/{link_id}")
def remove_team_link(team_id: int, link_id: int,
                     user=Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    role = _require_member(conn, team_id, user["id"])
    row = get_link(conn, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="链接不存在")

    if row["team_id"] == team_id:
        # 团队自有链接：创建者或拥有者可删
        if row["owner_user_id"] != user["id"] and role != "owner":
            raise HTTPException(status_code=403, detail="不能删除其他成员贡献的链接")
        conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        conn.commit()
        return {"ok": True, "action": "deleted"}

    # 成员共享的个人链接：本人取消共享，或拥有者移出团队
    share = conn.execute(
        "SELECT * FROM link_team_links WHERE link_id = ? AND team_id = ?",
        (link_id, team_id)).fetchone()
    if share is None:
        raise HTTPException(status_code=404, detail="该链接不在本团队空间中")
    if row["owner_user_id"] != user["id"] and role != "owner":
        raise HTTPException(status_code=403,
                            detail="这是别人共享的链接，只有本人或团队拥有者可以移出")

    conn.execute("DELETE FROM link_team_links WHERE link_id = ? AND team_id = ?",
                 (link_id, team_id))
    conn.commit()
    return {"ok": True, "action": "unshared"}


@router.post("/{team_id}/links/{link_id}/copy-to-personal")
def copy_to_personal(team_id: int, link_id: int, payload: CopyIn,
                     user=Depends(get_current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    _require_member(conn, team_id, user["id"])
    row = get_link(conn, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="链接不存在")

    visible = (row["team_id"] == team_id)
    if not visible:
        share = conn.execute(
            "SELECT 1 FROM link_team_links WHERE link_id = ? AND team_id = ? "
            "AND in_space = 1", (link_id, team_id)).fetchone()
        visible = share is not None
    if not visible:
        raise HTTPException(status_code=404, detail="该链接不在本团队空间中")

    if payload.group_id is not None:
        g = get_group(conn, payload.group_id)
        if g is None or g["scope"] != "personal" or g["owner_user_id"] != user["id"]:
            raise HTTPException(status_code=400, detail="个人分组不存在")

    now = utcnow()
    cur = conn.execute(
        "INSERT INTO links (owner_user_id, team_id, group_id, url, title, description,"
        " tags, favicon, copied_from_link_id, created_at, updated_at) "
        "VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], payload.group_id, row["url"], row["title"],
         row["description"], row["tags"], row["favicon"], link_id, now, now))
    conn.commit()
    out = serialize_link(get_link(conn, cur.lastrowid))
    out["shares"] = []
    return out


# ── 成员的个人空间（对该团队公开的链接）────────────────────────────────────

# 注：「成员个人空间页」接口（GET /{team_id}/members/{user_id}/links）已随
# 「对团队可见」功能一起下线——对外有公开页了，队友互看收藏这个中间态属于多余。

