#!/usr/bin/env python3
"""接口契约测试。

前端是按固定字段名读数据的（例如工作台卡片读 t.link_count）。
后端少给一个字段，前端不会报错，只会安静地显示 "undefined"——
所以这里把「前端依赖的字段」显式断言一遍。
"""
import sys

import httpx

import os

BASE = os.environ.get("MAGICLINK_BASE", "http://127.0.0.1:3030")
PASS, FAIL = 0, 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}   {extra}")


def main():
    c = httpx.Client(base_url=BASE, timeout=20)
    c.post("/api/auth/register", json={"username": "contract_u",
                                       "password": "pw123456",
                                       "display_name": "契约用户"})
    if c.get("/api/me").status_code != 200:
        c.post("/api/auth/login", json={"username": "contract_u",
                                        "password": "pw123456"})

    g = c.post("/api/local/groups", json={"name": "契约分组"}).json()
    c.post("/api/local/links", json={"url": "https://example.com", "title": "契约链接",
                                     "group_id": g["id"], "tags": ["a", "b"]})
    t = c.post("/api/teams", json={"name": "契约团队"}).json()
    c.post(f"/api/teams/{t['id']}/links", json={"url": "https://example.org", "title": "团队链接"})
    link_id = c.get("/api/local/links").json()["items"][0]["id"]
    c.put(f"/api/local/links/{link_id}/shares/{t['id']}",
          json={"in_space": True})

    print("=== /api/me ===")
    me = c.get("/api/me").json()
    check("有 user 对象", isinstance(me.get("user"), dict))
    check("user 有 display_name", "display_name" in me["user"])
    check("有 teams 数组", isinstance(me.get("teams"), list))
    tm = me["teams"][0]
    for f in ("id", "name", "role", "member_count", "link_count", "shared_count"):
        check(f"teams[0].{f} 存在", f in tm, f"实际字段={sorted(tm)}")

    print("=== /api/local/links ===")
    d = c.get("/api/local/links").json()
    for f in ("items", "total", "page", "page_size", "pages", "tags"):
        check(f"{f} 存在", f in d, f"实际={sorted(d)}")
    it = d["items"][0]
    for f in ("id", "url", "title", "description", "tags", "favicon", "group_name", "shares"):
        check(f"items[0].{f} 存在", f in it, f"实际={sorted(it)}")
    check("tags 是数组", isinstance(it["tags"], list))
    check("shares 是数组", isinstance(it["shares"], list))
    check("shares[0] 有 team_id/in_space",
          all(k in it["shares"][0] for k in ("team_id", "in_space")))

    print("=== /api/teams/{id}/links ===")
    tl = c.get(f"/api/teams/{t['id']}/links").json()
    kinds = {i["kind"] for i in tl["items"]}
    check("同时返回 team 和 shared 两种", kinds == {"team", "shared"}, f"实际={kinds}")
    si = next(i for i in tl["items"] if i["kind"] == "shared")
    for f in ("owner_name", "can_edit", "can_remove"):
        check(f"shared 项有 {f}", f in si, f"实际={sorted(si)}")

    print("=== /api/teams/{id} ===")
    td = c.get(f"/api/teams/{t['id']}").json()
    for f in ("id", "name", "invite_code", "my_role", "member_count",
              "link_count", "shared_count"):
        check(f"{f} 存在", f in td, f"实际={sorted(td)}")

    print("=== /api/teams/{id}/members ===")
    md = c.get(f"/api/teams/{t['id']}/members").json()
    check("items 是数组", isinstance(md.get("items"), list))
    check("成员有 contributed_count", "contributed_count" in md["items"][0])

    print()
    print("=" * 46)
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
