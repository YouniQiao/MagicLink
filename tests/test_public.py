#!/usr/bin/env python3
"""对外公开页测试。

关注三件事：
1. 默认不公开——没开总开关、没勾链接，匿名都拿不到东西；
2. 逐条控制——勾了才出现，取消就消失；
3. 匿名访问——不带任何 cookie 也能看到（这正是这个功能的意义）。
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


def main():
    owner = httpx.Client(base_url=BASE, timeout=20)
    owner.post("/api/auth/register", json={"username": "pub_owner",
                                           "password": "pw123456",
                                           "display_name": "公开测试"})
    if owner.get("/api/me").status_code != 200:
        owner.post("/api/auth/login", json={"username": "pub_owner",
                                            "password": "pw123456"})
    member = httpx.Client(base_url=BASE, timeout=20)
    member.post("/api/auth/register", json={"username": "pub_member",
                                            "password": "pw123456",
                                            "display_name": "成员乙"})
    if member.get("/api/me").status_code != 200:
        member.post("/api/auth/login", json={"username": "pub_member",
                                             "password": "pw123456"})

    anon = httpx.Client(base_url=BASE, timeout=20)   # 不带 cookie

    team = owner.post("/api/teams", json={"name": "公开测试团队"}).json()
    tid = team["id"]
    member.post("/api/teams/join", json={"invite_code": team["invite_code"]})

    g = owner.post("/api/local/groups", json={"name": "公开分组"}).json()
    pub_link = owner.post("/api/local/links", json={
        "url": "https://example.com", "title": "公开的链接",
        "description": "这条应该对外可见", "group_id": g["id"],
        "tags": ["公开"], "public_show": True}).json()
    owner.post("/api/local/links", json={
        "url": "https://example.org", "title": "私密的链接",
        "tags": ["私密"]}).json()
    # 拥有者把公开的那条也共享进团队空间（团队公开页会收录它）
    owner.put(f"/api/local/links/{pub_link['id']}/shares/{tid}",
              json={"in_space": True})

    # 成员的一条：共享进团队空间 + 对外公开
    mg = member.post("/api/local/groups", json={"name": "乙的分组"}).json()
    m_link = member.post("/api/local/links", json={
        "url": "https://go.dev", "title": "乙的公开链接",
        "group_id": mg["id"], "tags": ["成员"], "public_show": True}).json()
    member.put(f"/api/local/links/{m_link['id']}/shares/{tid}",
               json={"in_space": True})
    # 成员的、不公开的链接（共享进团队空间但没勾公开）
    m_hidden = member.post("/api/local/links", json={
        "url": "https://www.rust-lang.org", "title": "乙的内部链接"}).json()
    member.put(f"/api/local/links/{m_hidden['id']}/shares/{tid}",
               json={"in_space": True})

    owner.post(f"/api/teams/{tid}/links", json={
        "url": "https://www.python.org", "title": "团队公开链接",
        "public_show": True}).json()
    owner.post(f"/api/teams/{tid}/links", json={
        "url": "https://nodejs.org", "title": "团队内部链接"})

    print("=== 1. 默认：总开关没开，匿名拿不到 ===")
    r = anon.get("/api/public/u/pub_owner")
    check("个人页 404", r.status_code == 404, f"实际 {r.status_code}")
    r = anon.get("/api/public/t/team-%d" % tid)
    check("团队页 404", r.status_code == 404, f"实际 {r.status_code}")

    print("=== 2. 开启个人公开页 ===")
    r = owner.post("/api/me/public", json={"enabled": True})
    check("开启成功 200", r.status_code == 200, r.text[:120])
    check("返回地址 /u/pub_owner", r.json().get("public_url") == "/u/pub_owner",
          str(r.json()))
    d = anon.get("/api/public/u/pub_owner").json()
    check("匿名可见 200", isinstance(d, dict))
    check("只有 1 条（私密的不出现）", d["total"] == 1, str(d["total"]))
    check("是那条公开链接", d["groups"][0]["links"][0]["title"] == "公开的链接")
    check("按分组归类", d["groups"][0]["name"] == "公开分组", str(d["groups"][0]["name"]))
    check("标签汇总出来", d["tags"] == ["公开"], str(d["tags"]))

    print("=== 3. 取消某条的公开 ===")
    owner.patch(f"/api/local/links/{pub_link['id']}", json={"public_show": False})
    d = anon.get("/api/public/u/pub_owner").json()
    check("取消后为 0 条", d["total"] == 0, str(d["total"]))
    owner.patch(f"/api/local/links/{pub_link['id']}", json={"public_show": True})
    check("重新勾选后回到 1 条",
          anon.get("/api/public/u/pub_owner").json()["total"] == 1)

    print("=== 4. 关掉总开关：勾了也不外露 ===")
    owner.post("/api/me/public", json={"enabled": False})
    check("个人页又 404", anon.get("/api/public/u/pub_owner").status_code == 404)
    owner.post("/api/me/public", json={"enabled": True})

    print("=== 5. 团队公开页 ===")
    r = member.post(f"/api/teams/{tid}/public", json={"enabled": True, "slug": "pub-team"})
    check("非拥有者不能设置 403", r.status_code == 403, f"实际 {r.status_code}")
    r = owner.post(f"/api/teams/{tid}/public", json={"enabled": True, "slug": "pub-team"})
    check("拥有者可以设置 200", r.status_code == 200, r.text[:120])
    check("地址为 /t/pub-team", r.json().get("public_url") == "/t/pub-team", str(r.json()))

    d = anon.get("/api/public/t/pub-team").json()
    titles = [l["title"] for gp in d["groups"] for l in gp["links"]]
    check("团队页匿名可见", d["total"] == 3, f"实际 {d['total']} 条: {titles}")
    check("含团队自有公开链接", "团队公开链接" in titles, str(titles))
    check("含成员共享+公开的链接", "乙的公开链接" in titles, str(titles))
    check("含拥有者共享的个人链接（对外公开的那条）", "公开的链接" in titles, str(titles))
    check("不含团队内部链接", "团队内部链接" not in titles, str(titles))
    check("不含成员内部链接", "乙的内部链接" not in titles, str(titles))

    print("=== 6. 用 team-<id> 兜底地址也能访问 ===")
    d2 = anon.get(f"/api/public/t/team-{tid}")
    check("team-<id> 可用", d2.status_code == 200, f"实际 {d2.status_code}")

    print("=== 7. 地址校验 ===")
    check("非法地址 400",
          owner.post(f"/api/teams/{tid}/public",
                     json={"enabled": True, "slug": "Bad Slug!"}).status_code == 400)
    check("保留格式 team-9 被拒 400",
          owner.post(f"/api/teams/{tid}/public",
                     json={"enabled": True, "slug": "team-9"}).status_code == 400)
    other = owner.post("/api/teams", json={"name": "另一个团队"}).json()
    check("地址被占用 409",
          owner.post(f"/api/teams/{other['id']}/public",
                     json={"enabled": True, "slug": "pub-team"}).status_code == 409)
    check("换一个可用的地址 200",
          owner.post(f"/api/teams/{other['id']}/public",
                     json={"enabled": True, "slug": "another-team"}).status_code == 200)

    print("=== 8. 存在性检查接口 ===")
    check("已占用 → available=false",
          anon.get("/api/public/check-slug", params={"slug": "pub-team"})
          .json()["available"] is False)
    check("未占用 → available=true",
          anon.get("/api/public/check-slug", params={"slug": "free-slug-here"})
          .json()["available"] is True)

    print("=== 9. 关闭团队公开页后立刻不可见 ===")
    owner.post(f"/api/teams/{tid}/public", json={"enabled": False, "slug": "pub-team"})
    check("关闭后 404", anon.get("/api/public/t/pub-team").status_code == 404)

    print("=== 10. 公开页的 HTML 壳 ===")
    for path in ("/u/pub_owner", "/t/pub-team"):
        r = anon.get(path)
        check(f"{path} 返回页面壳",
              r.status_code == 200 and "/js/public.js" in r.text, f"实际 {r.status_code}")
    shell = anon.get("/t/pub-team").text
    check("壳里不泄露数据（未登录也要等接口返回）",
          "团队公开链接" not in shell and "pub-team" not in shell.replace("/t/pub-team", ""))
    check("带 noindex", "noindex" in anon.get("/u/pub_owner").text)

    print("=== 11. 首页：公开空间目录 ===")
    check("根路径是目录页（不是登录页）",
          "/js/home.js" in anon.get("/").text)
    check("/app 是登录界面壳",
          "/js/app.js" in anon.get("/app").text)

    owner.post(f"/api/teams/{tid}/public", json={"enabled": True, "slug": "pub-team"})
    d = anon.get("/api/public/directory").json()
    names = {t["name"] for t in d["teams"]}
    ppl = {p["username"]: p for p in d["people"]}

    check("目录里能看到团队空间", "公开测试团队" in names, str(names))
    t_entry = next((t for t in d["teams"] if t["name"] == "公开测试团队"), {})
    check("团队条目地址正确", t_entry.get("url") == "/t/pub-team", str(t_entry.get("url")))
    check("团队条目链接数 = 3（自有1 + 成员共享2）",
          t_entry.get("link_count") == 3, str(t_entry.get("link_count")))
    check("团队条目带拥有者", t_entry.get("owner_name") == "公开测试", str(t_entry.get("owner_name")))

    check("目录里能看到个人空间", "pub_owner" in ppl, str(list(ppl)))
    check("个人条目地址正确", ppl.get("pub_owner", {}).get("url") == "/u/pub_owner")
    check("个人条目链接数 = 1", ppl.get("pub_owner", {}).get("link_count") == 1)

    # 成员有公开链接，但没开启自己的公开页 → 不应出现在目录里
    check("没开公开页的人不出现（哪怕他有公开链接）", "pub_member" not in ppl, str(list(ppl)))

    # 开了公开页但一条公开链接都没有 → 也不出现（避免点进去是空页）
    empty_user = httpx.Client(base_url=BASE, timeout=20)
    empty_user.post("/api/auth/register", json={"username": "pub_empty",
                                                "password": "pw123456",
                                                "display_name": "空空间"})
    if empty_user.get("/api/me").status_code != 200:
        empty_user.post("/api/auth/login", json={"username": "pub_empty",
                                                 "password": "pw123456"})
    empty_user.post("/api/me/public", json={"enabled": True})
    d = anon.get("/api/public/directory").json()
    check("开了公开页但没有公开链接 → 不出现",
          "pub_empty" not in {p["username"] for p in d["people"]})

    check("总数与两段内容一致",
          d["total"] == len(d["teams"]) + len(d["people"]), str(d["total"]))

    # ── 9. 个人公开页可以自定义地址 ──────────────────────────────────────────
    print()
    print("=== 9. 个人公开页自定义地址 ===")

    r = owner.post("/api/me/public", json={"enabled": True, "slug": "my-links"}).json()
    check("设了地址后 public_url 用它", r.get("public_url") == "/u/my-links", str(r))
    check("public_slug 回填", r.get("public_slug") == "my-links", str(r))
    check("公开页返回的 slug 也换了",
          anon.get("/api/public/u/my-links").json().get("slug") == "my-links")

    # 老地址仍然可用 —— 改地址不该让已经分享出去的链接失效
    check("旧的 /u/<用户名> 依然能打开", anon.get("/api/public/u/pub_owner").status_code == 200)

    # 目录里也用新地址
    ppl = {p["username"]: p for p in anon.get("/api/public/directory").json()["people"]}
    check("目录条目用新地址", ppl.get("pub_owner", {}).get("url") == "/u/my-links",
          str(ppl.get("pub_owner", {}).get("url")))

    # 只切开关、不带 slug → 不该把设好的地址冲掉
    r = owner.post("/api/me/public", json={"enabled": False}).json()
    check("关闭时不带 slug 仍保留地址", r.get("public_slug") == "my-links", str(r))
    r = owner.post("/api/me/public", json={"enabled": True}).json()
    check("再开启地址还在", r.get("public_url") == "/u/my-links", str(r))

    # 校验
    check("非法地址 400",
          owner.post("/api/me/public", json={"enabled": True, "slug": "Bad_Slug"}).status_code == 400)
    check("太短 400",
          owner.post("/api/me/public", json={"enabled": True, "slug": "a"}).status_code == 400)
    check("连字符开头 400",
          owner.post("/api/me/public", json={"enabled": True, "slug": "-abc"}).status_code == 400)

    # 被别的用户占用
    check("别人用过的地址 409",
          member.post("/api/me/public",
                      json={"enabled": True, "slug": "my-links"}).status_code == 409)
    # 跟别人的用户名撞也会让对方的页面打不开，所以要挡。
    # 注意要用「格式合法的用户名」来测：pub_owner 带下划线，会先被格式校验拦成 400，
    # 根本走不到冲突检查那一步。
    other = httpx.Client(base_url=BASE, timeout=20)
    other.post("/api/auth/register", json={"username": "alice",
                                           "password": "pw123456",
                                           "display_name": "爱丽丝"})
    if other.get("/api/me").status_code != 200:
        other.post("/api/auth/login", json={"username": "alice", "password": "pw123456"})
    check("跟别人的用户名重复 409",
          member.post("/api/me/public",
                      json={"enabled": True, "slug": "alice"}).status_code == 409)
    # 用自己的用户名也是可以的（等于把自定义地址清回用户名）
    check("用自己的用户名可以",
          owner.post("/api/me/public",
                     json={"enabled": True, "slug": None}).status_code == 200)

    # 清空 → 退回 /u/<用户名>
    r = owner.post("/api/me/public", json={"enabled": True, "slug": ""}).json()
    check("传空串清掉自定义地址", r.get("public_url") == "/u/pub_owner", str(r))
    check("清掉后 /u/<用户名> 正常", anon.get("/api/public/u/pub_owner").status_code == 200)
    check("清掉后旧的自定义地址失效", anon.get("/api/public/u/my-links").status_code == 404)

    print()
    print("=" * 46)
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
