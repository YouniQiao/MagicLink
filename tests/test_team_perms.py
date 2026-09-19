#!/usr/bin/env python3
"""团队链接的权限矩阵 + 来源标记。

规则（用户明确要的）：

|            | 自己的团队链接 | 别人的团队链接 | 自己共享进来的 | 别人共享进来的 |
| 团队拥有者  | 改 ✓  删 ✓     | 改 ✓  删 ✓     | 改 ✓*  移出 ✓  | 改 ✗  移出 ✓   |
| 普通成员    | 改 ✓  删 ✓     | 改 ✗  删 ✗     | 改 ✓*  移出 ✓  | 改 ✗  移出 ✗   |
| 非成员      | 一律 403                                                |

*共享进来的链接内容归本人，得走 `/api/local/links/{id}` 改自己的那条；
团队接口对这类链接一律 400（「去个人空间改」）。

这套规则后端本来就在拦（403/400），真正容易错的是**前端拿到的
`can_edit` / `can_remove` 标志和接口实际结果不一致**——标志说能改、
点下去 403，界面在骗人。所以这里每个格子都同时断言两件事：
标志的值，以及真去打一次接口的结果。
"""
import os
import sys

import httpx

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


def user(name, display):
    c = httpx.Client(base_url=BASE, timeout=20)
    c.post("/api/auth/register", json={"username": name, "password": "pw123456",
                                       "display_name": display})
    if c.get("/api/me").status_code != 200:
        c.post("/api/auth/login", json={"username": name, "password": "pw123456"})
    return c


def items(client, tid):
    return client.get(f"/api/teams/{tid}/links",
                      params={"page_size": 500}).json()["items"]


def item_for(client, tid, link_id):
    return next((i for i in items(client, tid) if i["id"] == link_id), None)


def main():
    alice = user("perm_owner", "权限甲")     # 团队拥有者
    bob = user("perm_member", "权限乙")      # 普通成员
    carol = user("perm_outsider", "权限丙")  # 不是成员

    tid = alice.post("/api/teams", json={"name": "权限团队"}).json()["id"]
    invite = alice.get(f"/api/teams/{tid}").json()["invite_code"]
    bob.post("/api/teams/join", json={"invite_code": invite})

    # 四个格子：团队自有 × 2（甲建/乙建）+ 成员共享 × 2（甲共享/乙共享）
    ta = alice.post(f"/api/teams/{tid}/links",
                    json={"url": "https://e.com/ta", "title": "甲的团队链接"}).json()["id"]
    tb = bob.post(f"/api/teams/{tid}/links",
                  json={"url": "https://e.com/tb", "title": "乙的团队链接"}).json()["id"]

    sa = alice.post("/api/local/links",
                    json={"url": "https://e.com/sa", "title": "甲的个人链接"}).json()["id"]
    alice.put(f"/api/local/links/{sa}/shares/{tid}", json={"in_space": True})
    sb = bob.post("/api/local/links",
                  json={"url": "https://e.com/sb", "title": "乙的个人链接"}).json()["id"]
    bob.put(f"/api/local/links/{sb}/shares/{tid}", json={"in_space": True})

    print("\n=== 1. 来源：两种来源都能看出谁加的 ===")
    a_view = items(alice, tid)
    by_id = {i["id"]: i for i in a_view}
    check("团队链接带创建人（甲建的）", by_id[ta]["owner_name"] == "权限甲",
          repr(by_id[ta].get("owner_name")))
    check("团队链接带创建人（乙建的）", by_id[tb]["owner_name"] == "权限乙",
          repr(by_id[tb].get("owner_name")))
    check("共享链接带来源（乙的个人链接）", by_id[sb]["owner_name"] == "权限乙",
          repr(by_id[sb].get("owner_name")))
    check("团队自有链接标为 team", by_id[ta]["kind"] == "team")
    check("共享进来的标为 shared", by_id[sb]["kind"] == "shared")
    check("四种都有 owner_id", all(by_id[x].get("owner_id") for x in (ta, tb, sa, sb)))
    check("有创建人名字的团队链接已不再是空串",
          all(by_id[x]["owner_name"] for x in (ta, tb)))

    print("\n=== 2. 普通成员：只能动自己加的 ===")
    check("乙自己的团队链接 can_edit", item_for(bob, tid, tb)["can_edit"] is True)
    check("乙自己的团队链接 can_remove", item_for(bob, tid, tb)["can_remove"] is True)
    check("甲建的：can_edit=False", item_for(bob, tid, ta)["can_edit"] is False)
    check("甲建的：can_remove=False", item_for(bob, tid, ta)["can_remove"] is False)
    r = bob.patch(f"/api/teams/{tid}/links/{ta}", json={"title": "乙想改"})
    check("乙改甲建的 → 403", r.status_code == 403, str(r.status_code))
    r = bob.delete(f"/api/teams/{tid}/links/{ta}")
    check("乙删甲建的 → 403", r.status_code == 403, str(r.status_code))
    check("甲建的标题没被动", item_for(bob, tid, ta)["title"] == "甲的团队链接")
    r = bob.patch(f"/api/teams/{tid}/links/{tb}", json={"title": "乙改自己的"})
    check("乙改自己的 → 200", r.status_code == 200, r.text[:200])

    print("\n=== 3. 拥有者：能改能删所有团队链接 ===")
    check("甲的 can_edit（自己的）", item_for(alice, tid, ta)["can_edit"] is True)
    check("甲的 can_edit（乙建的）← 这轮修的",
          item_for(alice, tid, tb)["can_edit"] is True)
    check("甲的 can_remove（乙建的）", item_for(alice, tid, tb)["can_remove"] is True)
    r = alice.patch(f"/api/teams/{tid}/links/{tb}", json={"title": "甲改了乙的"})
    check("甲改乙建的 → 200", r.status_code == 200, r.text[:200])
    check("改动真的生效", item_for(alice, tid, tb)["title"] == "甲改了乙的")

    print("\n=== 4. 成员共享进来的：内容归本人，团队只能移出 ===")
    check("乙看自己共享的 can_edit", item_for(bob, tid, sb)["can_edit"] is True)
    check("乙看自己共享的 can_remove", item_for(bob, tid, sb)["can_remove"] is True)
    check("甲看乙共享的 can_edit=False（改不了内容）",
          item_for(alice, tid, sb)["can_edit"] is False)
    check("甲看乙共享的 can_remove=True（可以移出团队）",
          item_for(alice, tid, sb)["can_remove"] is True)
    check("甲看自己共享的 can_edit=True", item_for(alice, tid, sa)["can_edit"] is True)
    r = alice.patch(f"/api/teams/{tid}/links/{sb}", json={"title": "甲想改乙的个人链接"})
    check("甲改乙共享的 → 400（提示去个人空间改）", r.status_code == 400, r.text[:200])
    check("乙的个人链接内容没变", item_for(bob, tid, sb)["title"] == "乙的个人链接")
    r = bob.patch(f"/api/teams/{tid}/links/{sb}", json={"title": "乙自己改"})
    check("乙改自己共享的：团队接口也不行（400）", r.status_code == 400, str(r.status_code))
    r = bob.patch(f"/api/local/links/{sb}", json={"title": "乙自己改"})
    check("乙走个人接口改自己的 → 200", r.status_code == 200, r.text[:200])
    check("团队空间看到的就是新标题（引用同一份）",
          item_for(alice, tid, sb)["title"] == "乙自己改")

    print("\n=== 5. 标志不说谎：每个格子标志 == 接口实际结果 ===")
    # 每个格子都用一条新链接探测，避免互相影响
    def probe(client, who, link_id, tag, local_ok=False):
        it = item_for(client, tid, link_id)
        path = (f"/api/local/links/{link_id}" if local_ok
                else f"/api/teams/{tid}/links/{link_id}")
        r = client.patch(path, json={"description": "探针"})
        check(f"{who} 对{tag} can_edit={it['can_edit']} 与接口 {r.status_code} 一致",
              bool(it["can_edit"]) == (r.status_code == 200),
              f"flag={it['can_edit']} status={r.status_code}")
        it2 = item_for(client, tid, link_id)
        r2 = client.delete(f"/api/teams/{tid}/links/{link_id}")
        check(f"{who} 对{tag} can_remove={it2['can_remove']} 与接口 {r2.status_code} 一致",
              bool(it2["can_remove"]) == (r2.status_code == 200),
              f"flag={it2['can_remove']} status={r2.status_code}")

    # 拥有者视角
    lid = alice.post(f"/api/teams/{tid}/links",
                     json={"url": "https://e.com/p1", "title": "探针"}).json()["id"]
    probe(alice, "拥有者", lid, "自己建的团队链接")
    lid = bob.post(f"/api/teams/{tid}/links",
                   json={"url": "https://e.com/p2", "title": "探针"}).json()["id"]
    probe(alice, "拥有者", lid, "成员建的团队链接")
    lid = bob.post("/api/local/links",
                   json={"url": "https://e.com/p3", "title": "探针"}).json()["id"]
    bob.put(f"/api/local/links/{lid}/shares/{tid}", json={"in_space": True})
    probe(alice, "拥有者", lid, "成员共享的链接")

    # 普通成员视角
    lid = bob.post(f"/api/teams/{tid}/links",
                   json={"url": "https://e.com/p4", "title": "探针"}).json()["id"]
    probe(bob, "成员", lid, "自己建的团队链接")
    lid = alice.post(f"/api/teams/{tid}/links",
                     json={"url": "https://e.com/p5", "title": "探针"}).json()["id"]
    probe(bob, "成员", lid, "别人建的团队链接")
    lid = alice.post("/api/local/links",
                     json={"url": "https://e.com/p6", "title": "探针"}).json()["id"]
    alice.put(f"/api/local/links/{lid}/shares/{tid}", json={"in_space": True})
    probe(bob, "成员", lid, "别人共享的链接")

    print("\n=== 6. 移出团队 ≠ 删除链接本身 ===")
    r = alice.delete(f"/api/teams/{tid}/links/{sb}")
    check("拥有者移出乙共享的 → 200", r.status_code == 200, r.text[:200])
    check("团队空间里没有了", item_for(alice, tid, sb) is None)
    r = bob.get("/api/local/links", params={"page_size": 500})
    check("但乙的个人空间里还在",
          any(i["id"] == sb for i in r.json()["items"]), r.text[:200])

    print("\n=== 7. 非成员一律挡住 ===")
    r = carol.get(f"/api/teams/{tid}/links")
    check("非成员看列表 403", r.status_code == 403, str(r.status_code))
    r = carol.patch(f"/api/teams/{tid}/links/{ta}", json={"title": "x"})
    check("非成员改 403", r.status_code == 403, str(r.status_code))
    r = carol.delete(f"/api/teams/{tid}/links/{ta}")
    check("非成员删 403", r.status_code == 403, str(r.status_code))
    r = carol.post(f"/api/teams/{tid}/links", json={"url": "https://x.com"})
    check("非成员建 403", r.status_code == 403, str(r.status_code))

    print("\n=== 8. 创建人退队后，来源仍显示得出来 ===")
    tb2 = bob.post(f"/api/teams/{tid}/links",
                   json={"url": "https://e.com/tb2", "title": "乙退队前建的"}).json()["id"]
    bob.delete(f"/api/teams/{tid}/members/{bob.get('/api/me').json()['user']['id']}")
    it = item_for(alice, tid, tb2)
    check("人走了，来源还在", it is not None and it["owner_name"] == "权限乙",
          repr(it and it.get("owner_name")))
    check("拥有者仍可编辑他建的", item_for(alice, tid, tb2)["can_edit"] is True)

    print(f"\n结果: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
