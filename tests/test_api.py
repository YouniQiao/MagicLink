#!/usr/bin/env python3
"""MagicLink API 行为测试 —— 覆盖个人/团队空间、共享引用、权限边界。"""
import sys
import httpx

import os

BASE = os.environ.get("MAGICLINK_BASE", "http://127.0.0.1:3030")
PASS, FAIL = 0, 0
FAILURES = []


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}  {extra}")


def client():
    return httpx.Client(base_url=BASE, timeout=15, follow_redirects=True)


def register(c, username, pw="pw123456"):
    r = c.post("/api/auth/register",
               json={"username": username, "password": pw, "display_name": username})
    return r


print("=== 0. 注册 ===")
alice, bob, carol = client(), client(), client()
r = register(alice, "alice")
check("alice 注册 200", r.status_code == 200, r.text[:200])
r = register(bob, "bob")
check("bob 注册 200", r.status_code == 200, r.text[:200])
r = register(carol, "carol")
check("carol 注册 200", r.status_code == 200, r.text[:200])
r = register(client(), "alice")
check("重名注册 409", r.status_code == 409, r.text[:200])
r = client().post("/api/auth/login", json={"username": "alice", "password": "wrong"})
check("错误密码 401", r.status_code == 401, r.text[:200])

print("\n=== 1. 个人空间：分组 + 链接 ===")
r = alice.post("/api/local/groups", json={"name": "文档"})
check("建个人分组", r.status_code == 200, r.text[:200])
g_personal = r.json()["id"]

r = alice.post("/api/local/links", json={
    "url": "https://example.com/a", "title": "A 链接", "tags": ["docs"],
    "group_id": g_personal})
check("建个人链接", r.status_code == 200, r.text[:200])
link_personal = r.json()["id"]

r = alice.post("/api/local/links", json={"url": "https://example.com/b", "title": "B 链接"})
link_personal2 = r.json()["id"]

r = alice.get("/api/local/links")
d = r.json()
check("个人链接数 = 2", d["total"] == 2, str(d))
check("标签聚合含 docs", d["tags"] == ["docs"], str(d["tags"]))
r = alice.get("/api/local/links", params={"q": "B 链接"})
check("搜索命中 1 条", r.json()["total"] == 1, r.text[:200])
r = alice.get("/api/local/links", params={"group_id": g_personal})
check("按分组过滤 = 1", r.json()["total"] == 1, r.text[:200])
r = alice.get("/api/local/links", params={"ungrouped": True})
check("未分组 = 1", r.json()["total"] == 1, r.text[:200])

print("\n=== 2. 团队：创建 / 邀请码加入 ===")
r = alice.post("/api/teams", json={"name": "Docs 团队"})
check("alice 建团队", r.status_code == 200, r.text[:200])
team = r.json()["id"]
invite = r.json()["invite_code"]
check("拿到邀请码", bool(invite))

r = bob.post("/api/teams/join", json={"invite_code": invite})
check("bob 用邀请码加入", r.status_code == 200 and r.json()["role"] == "member", r.text[:200])
check("新加入的标 already_member=False", r.json().get("already_member") is False, r.text[:200])

# 邀请码大小写不敏感、前后空格无所谓
r = carol.post("/api/teams/join", json={"invite_code": f"  {invite.lower()}  "})
check("小写+带空格的邀请码照样能加入", r.status_code == 200, r.text[:200])
carol_id = carol.get("/api/me").json()["user"]["id"]
carol.delete(f"/api/teams/{team}/members/{carol_id}")   # 后面还要用 carol 测「非成员」

# 重复加入：不报错、不重复插成员、并且要能区分「本来就在」
r = bob.post("/api/teams/join", json={"invite_code": invite})
check("重复加入不报错", r.status_code == 200, r.text[:200])
check("重复加入标 already_member=True", r.json().get("already_member") is True, r.text[:200])
check("重复加入仍返回原角色", r.json()["role"] == "member", r.text[:200])
check("成员没被插两遍", len(alice.get(f"/api/teams/{team}/members").json()["items"]) == 2,
      r.text[:200])
# 拥有者点自己的邀请码：也算「本来就在」，且角色是 owner
r = alice.post("/api/teams/join", json={"invite_code": invite})
check("拥有者点自己的邀请码 = already_member", r.json().get("already_member") is True, r.text[:200])
check("拥有者角色不被降级", r.json()["role"] == "owner", r.text[:200])

r = carol.post("/api/teams/join", json={"invite_code": "BADCODE123"})
check("错误邀请码 404", r.status_code == 404, r.text[:200])

print("\n=== 2b. 重新生成邀请码（发出去的那串要能作废）===")
r = alice.post(f"/api/teams/{team}/invite/regenerate")
check("拥有者可以重新生成", r.status_code == 200, r.text[:200])
new_code = r.json()["invite_code"]
check("新邀请码和旧的不同", new_code and new_code != invite, f"{invite} -> {new_code}")
check("团队详情里已是新邀请码",
      alice.get(f"/api/teams/{team}").json()["invite_code"] == new_code)
r = bob.post(f"/api/teams/{team}/invite/regenerate")
check("普通成员不能重新生成 403", r.status_code == 403, r.text[:200])

dave = client()
dave.post("/api/auth/register", json={"username": "dave", "password": "pw123456",
                                      "display_name": "丁"})
r = dave.post("/api/teams/join", json={"invite_code": invite})
check("旧邀请码已失效 404", r.status_code == 404, r.text[:200])
r = dave.post("/api/teams/join", json={"invite_code": new_code})
check("新邀请码可用", r.status_code == 200, r.text[:200])
dave.delete(f"/api/teams/{team}/members/{dave.get('/api/me').json()['user']['id']}")

r = alice.post(f"/api/teams/{team}/groups", json={"name": "规范"})
check("建团队分组", r.status_code == 200, r.text[:200])
g_team = r.json()["id"]

r = alice.post(f"/api/teams/{team}/links", json={
    "url": "https://example.com/team1", "title": "团队链接1", "group_id": g_team})
check("alice 建团队链接", r.status_code == 200, r.text[:200])
team_link = r.json()["id"]

r = bob.post(f"/api/teams/{team}/links", json={
    "url": "https://example.com/team2", "title": "bob 的团队链接"})
check("bob 建团队链接", r.status_code == 200, r.text[:200])
team_link_bob = r.json()["id"]

r = carol.get(f"/api/teams/{team}/links")
check("非成员访问团队链接 403", r.status_code == 403, r.text[:200])

print("\n=== 3. 放进团队链接列表（引用同一份）===")
r = alice.put(f"/api/local/links/{link_personal}/shares/{team}",
              json={"in_space": True, "team_group_id": g_team})
check("把个人链接放进团队列表", r.status_code == 200, r.text[:200])

r = bob.get(f"/api/teams/{team}/links")
d = r.json()
kinds = {i["title"]: i["kind"] for i in d["items"]}
check("bob 看到 3 条团队可见链接", d["total"] == 3, str(d["total"]))
check("这条标记为 shared", kinds.get("A 链接") == "shared", str(kinds))
check("团队链接标记为 team", kinds.get("团队链接1") == "team", str(kinds))

# 引用语义：alice 改个人链接标题，bob 在团队里看到的是新标题
alice.patch(f"/api/local/links/{link_personal}", json={"title": "A 链接（已改名）"})
r = bob.get(f"/api/teams/{team}/links")
titles = [i["title"] for i in r.json()["items"]]
check("引用同一份：改动同步到团队", "A 链接（已改名）" in titles, str(titles))

# 移出团队列表
alice.put(f"/api/local/links/{link_personal}/shares/{team}",
          json={"in_space": False})
r = bob.get(f"/api/teams/{team}/links")
check("移出后不在团队链接列表", r.json()["total"] == 2, str(r.json()["total"]))
r = alice.get(f"/api/local/links/{link_personal}/shares")
check("移出后共享记录被清除", r.json()["items"] == [], r.text[:200])

# 恢复，供后续测试
alice.put(f"/api/local/links/{link_personal}/shares/{team}",
          json={"in_space": True, "team_group_id": g_team})

print("\n=== 3b. 已下线的「队友进我主页可见」不再存在 ===")
r = bob.get(f"/api/teams/{team}/members/{alice.get('/api/me').json()['user']['id']}/links")
check("该接口已移除（404）", r.status_code == 404, str(r.status_code))
r = bob.get(f"/api/teams/{team}/members")
check("成员列表不再返回 public_link_count",
      "public_link_count" not in r.json()["items"][0], str(r.json()["items"][0]))
check("成员列表改为返回 contributed_count",
      "contributed_count" in r.json()["items"][0])

print("\n=== 4. 权限边界 ===")
r = bob.patch(f"/api/teams/{team}/links/{team_link}", json={"title": "bob 想改"})
check("bob 改 alice 的团队链接 403", r.status_code == 403, r.text[:200])
r = bob.delete(f"/api/teams/{team}/links/{team_link}")
check("bob 删 alice 的团队链接 403", r.status_code == 403, r.text[:200])
r = alice.patch(f"/api/teams/{team}/links/{team_link}", json={"title": "团队链接1-改"})
check("alice 改自己的团队链接 200", r.status_code == 200, r.text[:200])
r = bob.delete(f"/api/teams/{team}/links/{team_link_bob}")
check("bob 删自己的团队链接 200", r.status_code == 200, r.text[:200])

r = bob.patch(f"/api/teams/{team}/links/{link_personal}", json={"title": "bob 越权改共享"})
check("bob 改 alice 共享的个人链接 400", r.status_code == 400, r.text[:200])
r = bob.delete(f"/api/teams/{team}/links/{link_personal}")
check("bob 移除 alice 的共享链接 403", r.status_code == 403, r.text[:200])
r = alice.delete(f"/api/teams/{team}/links/{link_personal}")
check("alice 自己能移出共享 200", r.status_code == 200, r.text[:200])
check("移出动作 = unshared", r.json().get("action") == "unshared", r.text[:200])
alice.put(f"/api/local/links/{link_personal}/shares/{team}",
          json={"in_space": True, "team_group_id": g_team})

r = carol.post(f"/api/teams/{team}/links", json={"url": "https://x.com", "title": "x"})
check("非成员建团队链接 403", r.status_code == 403, r.text[:200])

print("\n=== 5. 团队 -> 个人 复制（独立副本）===")
r = bob.post(f"/api/teams/{team}/links/{team_link}/copy-to-personal", json={})
check("复制团队链接到个人空间", r.status_code == 200, r.text[:200])
copied_id = r.json()["id"]
check("副本记录来源", r.json()["copied_from_link_id"] == team_link, r.text[:200])
r = bob.get("/api/local/links")
check("bob 个人空间有 1 条", r.json()["total"] == 1, r.text[:200])
# 独立副本：改副本不影响原链接
bob.patch(f"/api/local/links/{copied_id}", json={"title": "副本改名"})
r = alice.get(f"/api/teams/{team}/links")
check("改副本不影响团队里的原链接",
      all(i["title"] != "副本改名" for i in r.json()["items"]), r.text[:200])

print("\n=== 6. 成员管理 ===")
r = alice.get(f"/api/teams/{team}/members")
check("成员数 = 2", len(r.json()["items"]) == 2, r.text[:200])
r = bob.delete(f"/api/teams/{team}/members/{alice.get('/api/me').json()['user']['id']}")
check("bob 想移除 alice 403", r.status_code == 403, r.text[:200])
r = alice.get(f"/api/teams/{team}")
check("拥有者能看到邀请码", bool(r.json().get("invite_code")), r.text[:200])
r = bob.get(f"/api/teams/{team}")
check("成员看不到邀请码", r.json().get("invite_code") is None, r.text[:200])
r = bob.delete(f"/api/teams/{team}/members/{bob.get('/api/me').json()['user']['id']}")
check("成员可以自己退出", r.status_code == 200, r.text[:200])
r = alice.get(f"/api/teams/{team}/members")
check("退出后成员数 = 1", len(r.json()["items"]) == 1, r.text[:200])
r = alice.delete(f"/api/teams/{team}/members/{alice.get('/api/me').json()['user']['id']}")
check("拥有者不能退出 400", r.status_code == 400, r.text[:200])

print("\n=== 7. 改密码 / 登录 ===")
r = alice.post("/api/me/password", json={"old_password": "wrong", "new_password": "newpw123"})
check("原密码错 400", r.status_code == 400, r.text[:200])
r = alice.post("/api/me/password", json={"old_password": "pw123456", "new_password": "newpw123"})
check("改密码 200", r.status_code == 200, r.text[:200])
fresh = client()
r = fresh.post("/api/auth/login", json={"username": "alice", "password": "newpw123"})
check("新密码可登录", r.status_code == 200, r.text[:200])
r = client().post("/api/auth/login", json={"username": "alice", "password": "pw123456"})
check("旧密码失效 401", r.status_code == 401, r.text[:200])

print(f"\n{'='*46}\n结果: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("失败项:")
    for f in FAILURES:
        print("  -", f)
sys.exit(1 if FAIL else 0)
