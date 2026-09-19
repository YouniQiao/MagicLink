#!/usr/bin/env python3
"""MagicLink 运维命令（服务器上用，无需登录）。

用法：
  python manage.py init                          初始化数据库
  python manage.py list-users                    列出用户
  python manage.py demo                          造一套演示数据（本地看效果用）
  python manage.py demo --reset                  先清掉旧的演示数据再重造
  python manage.py reset-password <用户名>        重置密码（交互输入）
  python manage.py reset-password <用户名> -p 新密码
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.db import connect, init_db, utcnow
from app.security import hash_password, new_invite_code
from app.services import dump_tags

DEMO_USERS = ("demo1", "wang")
DEMO_PASSWORD = "demo1234"


def cmd_init(_args) -> int:
    init_db()
    print("数据库初始化完成")
    return 0


def cmd_list_users(_args) -> int:
    conn = connect()
    rows = conn.execute(
        "SELECT id, username, display_name, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    if not rows:
        print("（暂无用户）")
        return 0
    print(f"{'ID':>4}  {'用户名':<20} {'昵称':<20} 创建时间")
    for r in rows:
        print(f"{r['id']:>4}  {r['username']:<20} "
              f"{(r['display_name'] or ''):<20} {r['created_at']}")
    return 0


# ── 演示数据 ────────────────────────────────────────────────────────────────
# 一套能同时看到「个人空间 / 团队空间 / 共享 / 复制 / 分组 / 标签 / 公开页 /
# 权限差异」的最小数据。内容对应 README 里的截图。

def _fresh_invite_code(conn) -> str:
    for _ in range(5):
        code = new_invite_code()
        if conn.execute("SELECT 1 FROM teams WHERE invite_code = ?",
                        (code,)).fetchone() is None:
            return code
    raise SystemExit("生成邀请码失败，请重试")


def _add_user(conn, username: str, display: str, password: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, display_name, avatar,"
        " public_enabled, created_at) VALUES (?,?,?,'',1,?)",
        (username, hash_password(password), display, utcnow()))
    return cur.lastrowid


def _add_group(conn, *, scope, name, position=0, user_id=None, team_id=None) -> int:
    cur = conn.execute(
        "INSERT INTO groups (scope, owner_user_id, team_id, name, position, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (scope, user_id, team_id, name, position, utcnow()))
    return cur.lastrowid


def _add_link(conn, *, owner_id, url, title, description="", tags=(), favicon="",
              public=True, group_id=None, team_id=None, position=0,
              copied_from=None) -> int:
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO links (owner_user_id, team_id, group_id, url, title, description,"
        " tags, favicon, copied_from_link_id, public_show, position, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (owner_id, team_id, group_id, url, title, description, dump_tags(list(tags)),
         favicon, copied_from, 1 if public else 0, position, now, now))
    return cur.lastrowid


def _add_team(conn, *, name, owner_id, slug) -> int:
    cur = conn.execute(
        "INSERT INTO teams (name, owner_id, invite_code, public_enabled, public_slug,"
        " created_at) VALUES (?,?,?,1,?,?)",
        (name, owner_id, _fresh_invite_code(conn), slug, utcnow()))
    tid = cur.lastrowid
    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (tid, owner_id, "owner", utcnow()))
    return tid


def _add_member(conn, team_id: int, user_id: int) -> None:
    conn.execute(
        "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (team_id, user_id, "member", utcnow()))


def _add_share(conn, *, link_id, team_id, by, team_group_id=None, position=0) -> None:
    """把个人链接放进团队列表。in_profile 是废弃列，跟着写一样的值。"""
    conn.execute(
        "INSERT INTO link_team_links (link_id, team_id, in_space, in_profile,"
        " team_group_id, position, created_by, created_at) VALUES (?,?,1,1,?,?,?,?)",
        (link_id, team_id, team_group_id, position, by, utcnow()))


def _purge_demo(conn) -> None:
    """删掉演示账号及其数据。

    注意顺序：`teams.owner_id` 没有 ON DELETE CASCADE，直接删用户会撞外键，
    所以先删他们拥有的团队（团队一删，成员/团队分组/团队链接/共享记录都跟着走）。
    """
    holes = ",".join("?" * len(DEMO_USERS))
    conn.execute(f"DELETE FROM teams WHERE owner_id IN "
                 f"(SELECT id FROM users WHERE username IN ({holes}))", DEMO_USERS)
    conn.execute(f"DELETE FROM users WHERE username IN ({holes})", DEMO_USERS)


def cmd_demo(args) -> int:
    init_db()
    conn = connect()
    password = args.password or DEMO_PASSWORD
    holes = ",".join("?" * len(DEMO_USERS))

    existing = [r["username"] for r in conn.execute(
        f"SELECT username FROM users WHERE username IN ({holes})", DEMO_USERS)]

    if existing and not args.reset:
        print(f"已存在演示账号：{'、'.join(existing)}", file=sys.stderr)
        print("要重造请加 --reset（会把这两个账号及其团队一并删掉重来）", file=sys.stderr)
        conn.close()
        return 1

    if existing:
        _purge_demo(conn)
        print(f"· 已清掉旧的演示数据：{'、'.join(existing)}")

    # ── 两个账号 ──
    demo = _add_user(conn, "demo1", "演示用户", password)
    wang = _add_user(conn, "wang", "小王", password)

    # ── 演示用户的个人空间 ──
    g_docs = _add_group(conn, scope="personal", name="开发文档", position=0, user_id=demo)
    _add_group(conn, scope="personal", name="参考收藏", position=1, user_id=demo)  # 故意留空
    _add_link(conn, owner_id=demo, group_id=g_docs, position=0,
              url="https://www.python.org/", title="Welcome to Python.org",
              description="Python 官方网站，语言与标准库文档的入口。",
              tags=["参考"], favicon="https://www.python.org/static/favicon.ico")
    # 这条标题故意很长，用来顺带看看卡片标题的省略号表现
    _add_link(conn, owner_id=demo, group_id=g_docs, position=1,
              url="https://github.com/deskflow/deskflow",
              title="GitHub - deskflow/deskflow: Share a single keyboard and "
                    "mouse between multiple computers.",
              description="一套键鼠在多台电脑之间共享的开源方案。",
              tags=["工具", "开源"], favicon="https://github.com/favicon.ico")

    # ── 团队一：演示用户拥有，小王是成员 ──
    t_docs = _add_team(conn, name="文档技术组", owner_id=demo, slug="doc-team")
    _add_member(conn, t_docs, wang)
    tg_spec = _add_group(conn, scope="team", name="规范", position=0, team_id=t_docs)
    l_fastapi = _add_link(
        conn, owner_id=demo, team_id=t_docs, group_id=tg_spec, position=0,
        url="https://fastapi.tiangolo.com/",
        title="FastAPI 官方文档",
        description="本项目的框架文档，按教程与参考手册组织。",
        tags=["官方", "文档"], favicon="https://fastapi.tiangolo.com/img/favicon.png")

    # 小王的个人链接 -> 放进团队（团队侧会显示「来自 小王」）
    l_wang = _add_link(
        conn, owner_id=wang, position=0,
        url="https://developer.mozilla.org/",
        title="MDN Web Docs",
        description="Web 标准的权威参考，前端接口都查这里。",
        tags=["参考", "文档"], favicon="https://developer.mozilla.org/favicon.ico")
    _add_share(conn, link_id=l_wang, team_id=t_docs, by=wang)

    # 演示用户把团队那条「复制到我的空间」-> 独立副本，卡片上会标「来自团队复制」
    _add_link(conn, owner_id=demo, position=0, copied_from=l_fastapi,
              url="https://fastapi.tiangolo.com/",
              title="FastAPI 官方文档（我的副本）",
              description="从团队空间复制过来的独立副本，改这里不影响团队那条。",
              tags=["官方", "文档"], favicon="https://fastapi.tiangolo.com/img/favicon.png")

    # ── 团队二：小王拥有，演示用户是成员（演示「一个人可以属于多个团队」）──
    t_fe = _add_team(conn, name="前端小组", owner_id=wang, slug="fe-team")
    _add_member(conn, t_fe, demo)
    _add_link(conn, owner_id=wang, team_id=t_fe, position=0,
              url="https://vuejs.org/", title="Vue.js",
              description="渐进式 JavaScript 框架。", tags=["框架"],
              favicon="https://vuejs.org/logo.svg")
    # 这条不公开：用来演示「逐条勾选」——公开页上看不到它
    _add_link(conn, owner_id=wang, team_id=t_fe, position=1, public=False,
              url="https://vite.dev/", title="Vite",
              description="这条没勾「对外公开」，公开页上不会出现。",
              tags=["工具"], favicon="https://vite.dev/logo.svg")

    conn.commit()

    # 打印出来的地址要跟实际跑在哪一致：MAGICLINK_BASE_URL → PORT → 默认 3030
    base = (os.environ.get("MAGICLINK_BASE_URL") or
            "http://127.0.0.1:%s" % os.environ.get("PORT", "3030")).rstrip("/")

    print("""
演示数据已生成。

  账号（密码都是 %s）
    demo1   演示用户   拥有「文档技术组」，同时是「前端小组」的成员
    wang    小王       拥有「前端小组」，同时是「文档技术组」的成员

  个人空间            %s/app#/space
  团队空间            %s/app#/team/%d
  链接广场（首页）    %s/
  个人公开页          %s/u/demo1
  团队公开页          %s/t/doc-team
  另一个团队公开页    %s/t/fe-team

  这套数据里能看到：分组归类与拖拽排序、标签、逐条公开开关、
  个人空间 -> 团队列表（引用同一份）、团队 -> 个人（独立副本）、
  两级权限（拥有者能改删任意团队链接，普通成员只能动自己加的）。

  ⚠️ 这是给本地看效果用的：密码写死，别在对外可访问的实例上跑。
     重造：python manage.py demo --reset
""" % (password, base, base, t_docs, base, base, base, base))
    conn.close()
    return 0


def cmd_reset_password(args) -> int:
    conn = connect()
    row = conn.execute("SELECT id, username FROM users WHERE username = ?",
                       (args.username,)).fetchone()
    if row is None:
        print(f"找不到用户：{args.username}", file=sys.stderr)
        conn.close()
        return 1

    password = args.password
    if not password:
        password = getpass.getpass("新密码：")
        confirm = getpass.getpass("再输一次：")
        if password != confirm:
            print("两次输入不一致", file=sys.stderr)
            conn.close()
            return 1
    if len(password) < 6:
        print("密码至少 6 位", file=sys.stderr)
        conn.close()
        return 1

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (hash_password(password), row["id"]))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
    conn.commit()
    conn.close()
    print(f"已重置 {row['username']} 的密码（该用户所有登录状态已失效）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="MagicLink 运维命令")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化数据库")
    sub.add_parser("list-users", help="列出用户")

    d = sub.add_parser("demo", help="造一套演示数据（本地看效果用）")
    d.add_argument("--reset", action="store_true",
                   help="先删掉已有的演示账号及其团队，再重造")
    d.add_argument("-p", "--password", help=f"演示账号的密码（默认 {DEMO_PASSWORD}）")

    p = sub.add_parser("reset-password", help="重置某个用户的密码")
    p.add_argument("username")
    p.add_argument("-p", "--password", help="直接指定新密码（不给则交互输入）")

    args = parser.parse_args()
    handlers = {
        "init": cmd_init,
        "list-users": cmd_list_users,
        "demo": cmd_demo,
        "reset-password": cmd_reset_password,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
