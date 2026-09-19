#!/usr/bin/env python3
"""并发回归测试。

背景：FastAPI 把同步端点跑在线程池里，依赖函数和端点函数可能落在不同线程。
SQLite 连接默认禁止跨线程使用，一旦命中就是 500（而且顺序请求测不出来）。
这个文件专门用并发请求覆盖那类问题。
"""
import sys
import concurrent.futures as cf

import httpx

import os

BASE = os.environ.get("MAGICLINK_BASE", "http://127.0.0.1:3030")


def main():
    c = httpx.Client(base_url=BASE, timeout=20)
    user = "conc_user"
    c.post("/api/auth/register", json={"username": user, "password": "pw123456",
                                       "display_name": "并发测试"})
    if c.get("/api/me").status_code != 200:
        c.post("/api/auth/login", json={"username": user, "password": "pw123456"})
    assert c.get("/api/me").status_code == 200, "登录失败"

    team = c.post("/api/teams", json={"name": "并发团队"}).json()
    c.post("/api/teams/join", json={"invite_code": team["invite_code"]})
    grp = c.post("/api/local/groups", json={"name": "并发分组"}).json()
    c.post("/api/local/links", json={"url": "https://example.com", "title": "并发链接",
                                     "group_id": grp["id"], "tags": ["t1"]})

    paths = [
        ("GET", "/api/me", None),
        ("GET", "/api/local/groups", None),
        ("GET", "/api/local/links", None),
        ("GET", "/api/teams", None),
        ("GET", f"/api/teams/{team['id']}", None),
        ("GET", f"/api/teams/{team['id']}/members", None),
        ("GET", f"/api/teams/{team['id']}/groups", None),
        ("GET", f"/api/teams/{team['id']}/links", None),
    ]

    tasks = [paths[i % len(paths)] for i in range(64)]
    bad = []

    def hit(t):
        m, p, b = t
        r = c.request(m, p, json=b)
        if r.status_code != 200:
            bad.append((p, r.status_code, r.text[:120]))
        return r.status_code

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(hit, tasks))

    print(f"并发请求 {len(tasks)} 次，失败 {len(bad)} 次")
    for b in bad[:8]:
        print("   ✗", b)
    if bad:
        print("❌ 并发测试未通过")
        sys.exit(1)
    print("✅ 并发测试通过（无跨线程 500）")


if __name__ == "__main__":
    main()
