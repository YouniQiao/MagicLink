#!/usr/bin/env python3
"""拖拽排序测试。

这个功能的价值全在「排序结果被存下来、并且公开页看到的是同一个顺序」，
所以这里不测前端，只盯住数据那条链路：

1. 重排接口真的改顺序，并且顺序在重新拉取时保持；
2. 重排接口不是后门——别人的链接、别的分组的链接、别的团队的链接都改不动；
3. 新加的东西排在最后，不打扰已经拖好的顺序；
4. 换分组之后落到新分组的末尾；
5. 公开页读的是同一份 position，所以 /app 排完公开页跟着变。
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


def ids(client, path, **params):
    r = client.get(path, params=params or None)
    return [i["id"] for i in r.json()["items"]]


def main():
    # ── 准备：owner 两个分组 + 5 条链接；member 一个分组 + 1 条链接 ──
    owner = httpx.Client(base_url=BASE, timeout=20)
    owner.post("/api/auth/register", json={"username": "ord_owner",
                                           "password": "pw123456",
                                           "display_name": "排序甲"})
    if owner.get("/api/me").status_code != 200:
        owner.post("/api/auth/login", json={"username": "ord_owner",
                                            "password": "pw123456"})
    member = httpx.Client(base_url=BASE, timeout=20)
    member.post("/api/auth/register", json={"username": "ord_member",
                                            "password": "pw123456",
                                            "display_name": "排序乙"})
    if member.get("/api/me").status_code != 200:
        member.post("/api/auth/login", json={"username": "ord_member",
                                             "password": "pw123456"})

    g1 = owner.post("/api/local/groups", json={"name": "排序组一"}).json()
    g2 = owner.post("/api/local/groups", json={"name": "排序组二"}).json()
    g3 = owner.post("/api/local/groups", json={"name": "排序组三"}).json()
    gm = member.post("/api/local/groups", json={"name": "乙的组"}).json()

    def mk(client, i, group_id, show=False):
        return client.post("/api/local/links", json={
            "url": f"https://example.com/sort/{i}", "title": f"S{i}",
            "group_id": group_id, "public_show": show,
        }).json()["id"]

    a = [mk(owner, i, g1["id"], show=True) for i in range(1, 5)]
    u = [mk(owner, i, None) for i in (5, 6)]          # 未分组
    other = mk(member, 99, gm["id"])
    m_in_g1 = mk(member, 98, None)

    print("\n=== 1. 新分组排最后 ===")
    r = owner.get("/api/local/groups").json()["items"]
    check("三个分组按创建顺序", [g["id"] for g in r] == [g1["id"], g2["id"], g3["id"]],
          str([(g["id"], g["position"]) for g in r]))
    check("position 是 0/1/2", [g["position"] for g in r] == [0, 1, 2],
          str([g["position"] for g in r]))

    print("\n=== 2. 拖链接：组内顺序真的改并保持 ===")
    before = ids(owner, "/api/local/links", group_id=g1["id"])
    check("初始顺序 = 创建顺序", before == a, f"{before} vs {a}")
    new = [a[3], a[0], a[2], a[1]]
    r = owner.post("/api/local/links/reorder", json={"group_id": g1["id"], "items": new})
    check("重排 200", r.status_code == 200, r.text[:200])
    check("四条都动了", r.json()["moved"] == 4, r.text[:200])
    check("重新拉取顺序保持", ids(owner, "/api/local/links", group_id=g1["id"]) == new,
          str(ids(owner, "/api/local/links", group_id=g1["id"])))
    check("position 写成 0..3",
          [i["position"] for i in owner.get("/api/local/links",
                                            params={"group_id": g1["id"]}).json()["items"]]
          == [0, 1, 2, 3])

    print("\n=== 3. 重排不是后门 ===")
    r = owner.post("/api/local/links/reorder",
                   json={"group_id": g1["id"], "items": [other, m_in_g1] + new})
    check("别人的链接被忽略", r.json()["moved"] == 4, r.text[:200])
    check("别人的链接顺序没变",
          ids(member, "/api/local/links", group_id=gm["id"]) == [other])

    r = owner.post("/api/local/links/reorder",
                   json={"group_id": g2["id"], "items": new})   # 这批链接不在 g2
    check("分组对不上就不动", r.json()["moved"] == 0, r.text[:200])
    check("原分组顺序没被带跑",
          ids(owner, "/api/local/links", group_id=g1["id"]) == new)

    print("\n=== 4. 未分组也单独排 ===")
    r = owner.post("/api/local/links/reorder",
                   json={"group_id": None, "items": [u[1], u[0]]})
    check("未分组重排成功", r.json()["moved"] == 2, r.text[:200])
    check("未分组顺序 = 手动顺序",
          ids(owner, "/api/local/links", ungrouped=True) == [u[1], u[0]],
          str(ids(owner, "/api/local/links", ungrouped=True)))
    # 全量列表里，未分组永远在最后
    all_ids = ids(owner, "/api/local/links", page_size=100)
    check("未分组排在有名分组之后", all_ids[-2:] == [u[1], u[0]], str(all_ids))

    print("\n=== 5. 新链接排在该分组最后，不打乱已排好的顺序 ===")
    fresh = mk(owner, 7, g1["id"])
    check("新链接在组尾",
          ids(owner, "/api/local/links", group_id=g1["id"]) == new + [fresh],
          str(ids(owner, "/api/local/links", group_id=g1["id"])))

    print("\n=== 6. 换分组后落到新分组末尾 ===")
    owner.patch(f"/api/local/links/{fresh}", json={"group_id": g2["id"]})
    check("不在原分组了", fresh not in ids(owner, "/api/local/links", group_id=g1["id"]))
    check("出现在新分组末尾",
          ids(owner, "/api/local/links", group_id=g2["id"])[-1] == fresh,
          str(ids(owner, "/api/local/links", group_id=g2["id"])))
    owner.patch(f"/api/local/links/{fresh}", json={"clear_group": True})
    check("移出分组后进未分组", fresh in ids(owner, "/api/local/links", ungrouped=True))

    print("\n=== 7. 拖分组 ===")
    r = owner.post("/api/local/groups/reorder",
                   json={"items": [g3["id"], g1["id"], g2["id"]]})
    check("分组重排 200", r.status_code == 200, r.text[:200])
    order = [g["id"] for g in owner.get("/api/local/groups").json()["items"]]
    check("分组顺序 = 拖拽顺序", order == [g3["id"], g1["id"], g2["id"]], str(order))

    r = owner.post("/api/local/groups/reorder",
                   json={"items": [gm["id"], g3["id"], g1["id"], g2["id"]]})
    check("别人的分组被忽略", r.json()["moved"] == 3, r.text[:200])
    order = [g["id"] for g in owner.get("/api/local/groups").json()["items"]]
    check("自己的分组照常排好", order == [g3["id"], g1["id"], g2["id"]], str(order))
    check("别人的分组没被动",
          [g["id"] for g in member.get("/api/local/groups").json()["items"]]
          == [gm["id"]])

    print("\n=== 8. 公开页跟着 /app 走 ===")
    check("owner 公开页已关（还没开总开关）",
          httpx.get(f"{BASE}/api/public/u/ord_owner", timeout=20).status_code == 404)
    owner.post("/api/me/public", json={"enabled": True})
    pub = httpx.get(f"{BASE}/api/public/u/ord_owner", timeout=20)
    check("开启后匿名可见", pub.status_code == 200, str(pub.status_code))
    g = next(x for x in pub.json()["groups"] if x["id"] == g1["id"])
    check("公开页组内顺序 = /app 拖出来的顺序",
          [l["id"] for l in g["links"]] == new, str([l["id"] for l in g["links"]]))

    # /app 里再拖一次，公开页应该立刻跟着变
    newer = [new[2], new[3], new[0], new[1]]
    owner.post("/api/local/links/reorder", json={"group_id": g1["id"], "items": newer})
    pub2 = httpx.get(f"{BASE}/api/public/u/ord_owner", timeout=20).json()
    g2p = next(x for x in pub2["groups"] if x["id"] == g1["id"])
    check("再拖一次公开页同步",
          [l["id"] for l in g2p["links"]] == newer, str([l["id"] for l in g2p["links"]]))

    # 只公开了一部分时，公开页按 subset 的相对顺序排
    owner.patch(f"/api/local/links/{newer[1]}", json={"public_show": False})
    pub3 = httpx.get(f"{BASE}/api/public/u/ord_owner", timeout=20).json()
    g3p = next(x for x in pub3["groups"] if x["id"] == g1["id"])
    expect = [x for x in newer if x != newer[1]]
    check("取消公开后剩下的仍按同一顺序",
          [l["id"] for l in g3p["links"]] == expect, str([l["id"] for l in g3p["links"]]))

    print("\n=== 9. 团队空间：两种来源共用一个顺序 ===")
    tid = owner.post("/api/teams", json={"name": "排序团队"}).json()["id"]
    # member 要真在队里，才能把自己的个人链接放进来
    invite = owner.get(f"/api/teams/{tid}").json()["invite_code"]
    r = member.post("/api/teams/join", json={"invite_code": invite})
    check("乙加入团队", r.status_code == 200, r.text[:200])
    tg1 = owner.post(f"/api/teams/{tid}/groups", json={"name": "团队组一"}).json()
    tg2 = owner.post(f"/api/teams/{tid}/groups", json={"name": "团队组二"}).json()
    check("团队新分组排最后", tg2["position"] == 1, str(tg2["position"]))

    t_a = owner.post(f"/api/teams/{tid}/links",
                     json={"url": "https://example.com/t/a", "title": "TA",
                           "group_id": tg1["id"]}).json()["id"]
    t_b = owner.post(f"/api/teams/{tid}/links",
                     json={"url": "https://example.com/t/b", "title": "TB",
                           "group_id": tg1["id"]}).json()["id"]
    # member 把自己的个人链接放进团队组一
    s_c = mk(member, 97, gm["id"])
    r = member.put(f"/api/local/links/{s_c}/shares/{tid}",
                   json={"in_space": True, "team_group_id": tg1["id"]})
    check("个人链接进团队组一", r.status_code == 200, r.text[:200])
    check("放进团队后排在团队组一末尾",
          [(i["kind"], i["id"]) for i in
           owner.get(f"/api/teams/{tid}/links").json()["items"]
           if i["group_id"] == tg1["id"]] == [("team", t_a), ("team", t_b), ("shared", s_c)],
          str([(i["kind"], i["id"]) for i in
               owner.get(f"/api/teams/{tid}/links").json()["items"]]))

    # 拖成 shared, team, team
    r = owner.post(f"/api/teams/{tid}/links/reorder", json={
        "group_id": tg1["id"],
        "items": [{"kind": "shared", "id": s_c},
                  {"kind": "team", "id": t_b},
                  {"kind": "team", "id": t_a}],
    })
    check("团队链接重排 200", r.status_code == 200, r.text[:200])
    check("两个来源都动了", r.json()["moved"] == 3, r.text[:200])
    got = [(i["kind"], i["id"]) for i in owner.get(f"/api/teams/{tid}/links").json()["items"]
           if i["group_id"] == tg1["id"]]
    check("顺序保持（个人链接排到了最前）",
          got == [("shared", s_c), ("team", t_b), ("team", t_a)], str(got))

    # 非成员不能重排
    outsider = httpx.Client(base_url=BASE, timeout=20)
    outsider.post("/api/auth/register", json={"username": "ord_out",
                                              "password": "pw123456"})
    r = outsider.post(f"/api/teams/{tid}/links/reorder",
                      json={"group_id": tg1["id"], "items": []})
    check("非成员重排团队链接 403", r.status_code == 403, str(r.status_code))

    # 团队分组拖拽
    r = owner.post(f"/api/teams/{tid}/groups/reorder",
                   json={"items": [tg2["id"], tg1["id"]]})
    check("团队分组重排 200", r.status_code == 200, r.text[:200])
    check("团队分组顺序变了",
          [g["id"] for g in owner.get(f"/api/teams/{tid}/groups").json()["items"]]
          == [tg2["id"], tg1["id"]])

    print("\n=== 10. 团队公开页同样同步 ===")
    owner.post(f"/api/teams/{tid}/public", json={"enabled": True, "slug": "sort-team"})
    owner.patch(f"/api/teams/{tid}/links/{t_a}", json={"public_show": True})
    owner.patch(f"/api/teams/{tid}/links/{t_b}", json={"public_show": True})
    member.patch(f"/api/local/links/{s_c}", json={"public_show": True})
    tp = httpx.get(f"{BASE}/api/public/t/sort-team", timeout=20)
    check("团队公开页能打开", tp.status_code == 200, str(tp.status_code))
    tg = next(x for x in tp.json()["groups"] if x["id"] == tg1["id"])
    check("团队公开页顺序 = 拖出来的顺序",
          [l["id"] for l in tg["links"]] == [s_c, t_b, t_a],
          str([l["id"] for l in tg["links"]]))

    print(f"\n结果: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
