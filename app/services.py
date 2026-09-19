"""Shared helpers: link serialization, filtering, pagination, permissions."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

LINK_SELECT = (
    "SELECT l.*, g.name AS group_name, g.position AS group_position "
    "FROM links l LEFT JOIN groups g ON g.id = l.group_id "
)

# 列表顺序：先按分组的 position（未分组永远排最后），再按链接在组内的 position。
# 一路用 SQL 排好，Python 侧只在「合并两个来源」时用 sort_links() 复现同样的顺序。
LINK_ORDER_BY = ("(g.position IS NULL), g.position, g.name, "
                 "l.position, l.updated_at DESC, l.id DESC")


def parse_tags(raw: str) -> list[str]:
    try:
        tags = json.loads(raw or "[]")
        if isinstance(tags, list):
            return [str(t).strip() for t in tags if str(t).strip()]
    except Exception:
        pass
    return []


def dump_tags(tags: Optional[list[str]]) -> str:
    if not tags:
        return "[]"
    clean: list[str] = []
    for t in tags:
        t = str(t).strip()
        if t and t not in clean:
            clean.append(t)
    return json.dumps(clean, ensure_ascii=False)


def serialize_link(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = parse_tags(d.get("tags", "[]"))
    d["group_name"] = d.get("group_name") or ""
    # group_position 为 None 表示「未分组」，要保留这个信号（未分组排最后）
    d["position"] = d.get("position") or 0
    return d


def link_sort_key(d: dict) -> tuple:
    gp = d.get("group_position")
    return (gp is None, gp or 0, d.get("position") or 0, d.get("id") or 0)


def sort_links(items: list[dict]) -> list[dict]:
    """复现 SQL 的 LINK_ORDER_BY。

    团队空间要合并「团队自有链接」和「成员放进来的个人链接」两个来源，
    两边各自有序、拼起来就乱了，所以合完再按同一把尺子排一次。
    Python 的 sort 是稳定的：先按更新时间倒序垫底，再按分组/位置排，
    于是「组内 position 全为 0」的组就自然退化成更新时间倒序。
    """
    items.sort(key=lambda d: (d.get("updated_at") or "", d.get("id") or 0),
               reverse=True)
    items.sort(key=link_sort_key)
    return items


def next_group_position(conn: sqlite3.Connection, *, scope: str,
                        owner_user_id: Optional[int] = None,
                        team_id: Optional[int] = None) -> int:
    """新分组排在最后。"""
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM groups "
        "WHERE scope = ? AND IFNULL(owner_user_id, 0) = IFNULL(?, 0) "
        "  AND IFNULL(team_id, 0) = IFNULL(?, 0)",
        (scope, owner_user_id, team_id)).fetchone()
    return row["p"]


def next_link_position(conn: sqlite3.Connection, *,
                       owner_user_id: Optional[int] = None,
                       team_id: Optional[int] = None,
                       group_id: Optional[int] = None) -> int:
    """新链接排在其所在分组的最后（不打扰用户已经拖好的顺序）。"""
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM links "
        "WHERE IFNULL(team_id, 0) = IFNULL(?, 0) "
        "  AND owner_user_id = IFNULL(?, owner_user_id) "
        "  AND IFNULL(group_id, 0) = IFNULL(?, 0)",
        (team_id, owner_user_id, group_id)).fetchone()
    return row["p"]


def next_team_link_position(conn: sqlite3.Connection, *, team_id: int,
                            group_id: Optional[int] = None) -> int:
    """团队分组里下一个顺序号。

    团队空间一个分组里可能同时有「团队自有链接」（存在 links.position）和
    「成员放进来的个人链接」（存在 link_team_links.position），而列表是两者按
    position 合起来排的——所以必须取两边的最大值再 +1，各算各的会撞号，
    新放进来的链接就会插到别人中间去。
    """
    own = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM links "
        "WHERE team_id = ? AND IFNULL(group_id, 0) = IFNULL(?, 0)",
        (team_id, group_id)).fetchone()["p"]
    shared = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM link_team_links "
        "WHERE team_id = ? AND IFNULL(team_group_id, 0) = IFNULL(?, 0)",
        (team_id, group_id)).fetchone()["p"]
    return max(own, shared)


def build_filters(*, q: str = "", tag: str = "", group_id: Optional[int] = None,
                  ungrouped: bool = False) -> tuple[str, list[Any]]:
    sql, params = "", []
    if q:
        like = f"%{q.strip()}%"
        sql += (" AND (l.title LIKE ? OR l.url LIKE ? "
                " OR l.description LIKE ? OR l.tags LIKE ?)")
        params += [like, like, like, like]
    if tag:
        # tags 存为 JSON 数组，带引号匹配避免子串误命中
        sql += " AND l.tags LIKE ?"
        params.append(f'%"{tag.strip()}"%')
    if ungrouped:
        sql += " AND l.group_id IS NULL"
    elif group_id is not None:
        sql += " AND l.group_id = ?"
        params.append(group_id)
    return sql, params


def query_links(conn: sqlite3.Connection, base_where: str, base_params: list,
                *, q: str = "", tag: str = "", group_id: Optional[int] = None,
                ungrouped: bool = False, page: int = 1,
                page_size: int = 100) -> dict:
    extra, extra_params = build_filters(q=q, tag=tag, group_id=group_id,
                                        ungrouped=ungrouped)
    where = base_where + extra
    params = base_params + extra_params

    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM links l WHERE {where}", params).fetchone()["c"]

    page = max(1, page)
    page_size = max(1, min(500, page_size))
    offset = (page - 1) * page_size
    rows = conn.execute(
        LINK_SELECT + f"WHERE {where} ORDER BY {LINK_ORDER_BY} "
        f"LIMIT ? OFFSET ?", params + [page_size, offset]).fetchall()

    return {
        "items": [serialize_link(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def get_shares(conn: sqlite3.Connection, link_id: int) -> list[dict]:
    """这条个人链接出现在哪些团队。

    只返回「出现在团队链接列表」的团队（in_space）。曾经的 in_profile
    （队友进我主页能看到）已随该功能下线，列留着仅为兼容旧数据。
    """
    rows = conn.execute(
        "SELECT ltl.team_id, ltl.in_space, ltl.team_group_id, "
        "       t.name AS team_name, g.name AS team_group_name "
        "FROM link_team_links ltl "
        "JOIN teams t ON t.id = ltl.team_id "
        "LEFT JOIN groups g ON g.id = ltl.team_group_id "
        "WHERE ltl.link_id = ? AND ltl.in_space = 1 ORDER BY t.id",
        (link_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["in_space"] = bool(d["in_space"])
        d["team_group_name"] = d.get("team_group_name") or ""
        out.append(d)
    return out


def get_group(conn: sqlite3.Connection, group_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM groups WHERE id = ?",
                        (group_id,)).fetchone()


def get_link(conn: sqlite3.Connection, link_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(LINK_SELECT + "WHERE l.id = ?", (link_id,)).fetchone()


def link_tags_all(conn: sqlite3.Connection, where: str, params: list) -> list[str]:
    """All tags used by links matching a scope (for the filter bar)."""
    rows = conn.execute(
        f"SELECT DISTINCT l.tags AS tags FROM links l WHERE {where}", params
    ).fetchall()
    seen: list[str] = []
    for r in rows:
        for t in parse_tags(r["tags"]):
            if t not in seen:
                seen.append(t)
    return sorted(seen)
