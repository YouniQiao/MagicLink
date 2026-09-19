#!/usr/bin/env python3
"""GitCode 登录端到端测试。

不需要真实凭据：本地起一个假的 GitCode（只实现 token 和 user 两个接口），
让 MagicLink 指向它，就能把整条链路跑通——
  授权跳转 → 回调 state 校验 → 换 token → 取资料 → 建号/登录 → 会话生效。

这样测的是真实的代码路径（只有外部服务是假的），比只测「函数被调用了」有意义得多。
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = 0, 0

# 假 GitCode 会返回的资料，测试里按需替换
PROFILE = {
    "id": "64e5ed8f7e20aa73efcbc302",
    "login": "gc-user",
    "name": "示例用户",
    "avatar_url": "https://cdn-img.gitcode.com/fake.png",
    "email": "dev@example.com",
}
TOKEN_OK = True


class FakeGitCode(http.server.BaseHTTPRequestHandler):
    # 必须声明 1.1 并正确收发 Content-Length：否则 keep-alive 下没读完的
    # 请求体会把连接搞乱，客户端看到的是 "Connection reset by peer"。
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

    def do_POST(self):
        self._drain()
        if self.path.startswith("/oauth/token"):
            if not TOKEN_OK:
                self._send(400, {"error": "invalid_grant"})
                return
            self._send(200, {"access_token": "fake-token", "expires_in": 1296000})
            return
        self._send(404, {"error": "not found"})

    def do_GET(self):
        if self.path.startswith("/api/v5/user"):
            if self.headers.get("Authorization") != "Bearer fake-token":
                self._send(401, {"error": "bad token"})
                return
            self._send(200, dict(PROFILE))
            return
        self._send(404, {"error": "not found"})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}   {extra}")


def start_magiclink(port: int, db: Path, fake_port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "MAGICLINK_DB": str(db),
        "MAGICLINK_BASE_URL": f"http://127.0.0.1:{port}",
        "GITCODE_CLIENT_ID": "test-client-id",
        "GITCODE_CLIENT_SECRET": "test-secret",
        "GITCODE_AUTHORIZE_URL": f"http://127.0.0.1:{fake_port}/oauth/authorize",
        "GITCODE_TOKEN_URL": f"http://127.0.0.1:{fake_port}/oauth/token",
        "GITCODE_USER_API": f"http://127.0.0.1:{fake_port}/api/v5/user",
    })
    # 让 .env 不要覆盖测试用的值：测试变量已在环境里，config 只做 setdefault
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise RuntimeError("MagicLink 没起来：" + proc.stdout.read().decode()[:800])


def main():
    global TOKEN_OK
    fake_port, app_port = free_port(), free_port()

    fake = http.server.ThreadingHTTPServer(("127.0.0.1", fake_port), FakeGitCode)
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp())
    db = tmp / "test.db"
    subprocess.run([str(ROOT / ".venv/bin/python"), "manage.py", "init"],
                   cwd=ROOT, env={**os.environ, "MAGICLINK_DB": str(db)},
                   capture_output=True)
    proc = start_magiclink(app_port, db, fake_port)
    base = f"http://127.0.0.1:{app_port}"

    try:
        anon = httpx.Client(base_url=base, timeout=20)

        print("=== 1. status（前端据此决定要不要显示按钮）===")
        d = anon.get("/api/auth/gitcode/status").json()
        check("已启用", d["enabled"] is True, str(d))
        check("返回 client_id", d["client_id"] == "test-client-id", str(d))

        print("=== 2. 授权跳转 ===")
        r = anon.get("/api/auth/gitcode/start", follow_redirects=False)
        check("302 跳转", r.status_code == 302, str(r.status_code))
        loc = r.headers["location"]
        check("跳到 authorize 地址", loc.startswith(f"http://127.0.0.1:{fake_port}/oauth/authorize"), loc)
        check("带 client_id", "client_id=test-client-id" in loc)
        check("带 response_type=code", "response_type=code" in loc)
        check("带 scope=user_info", "scope=user_info" in loc)
        check("redirect_uri 指向本机回调",
              f"redirect_uri=http%3A%2F%2F127.0.0.1%3A{app_port}%2Fapi%2Fauth%2Fgitcode%2Fcallback" in loc, loc)
        check("种了 state cookie", "ml_oauth" in r.cookies, str(dict(r.cookies)))
        check("cookie 里记录了 login 用途", r.cookies["ml_oauth"].endswith("|login|"),
              r.cookies["ml_oauth"])

        print("=== 3. 回调：各种异常都要优雅处理 ===")
        r = anon.get("/api/auth/gitcode/callback?code=x&state=wrong", follow_redirects=False)
        check("state 不匹配 → 回登录页报错",
              r.status_code == 302 and "auth_error" in r.headers["location"],
              r.headers.get("location", ""))
        r = anon.get("/api/auth/gitcode/callback", follow_redirects=False)
        check("缺参数 → 回登录页报错", "auth_error" in r.headers.get("location", ""))
        r = anon.get("/api/auth/gitcode/callback?error=access_denied&error_description=用户拒绝",
                     follow_redirects=False)
        check("GitCode 返回 error → 原样带回来",
              "auth_error" in r.headers.get("location", ""))

        print("=== 4. 换 token 失败要能兜住 ===")
        TOKEN_OK = False
        c = httpx.Client(base_url=base, timeout=20)
        r0 = c.get("/api/auth/gitcode/start", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        r = c.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        check("换取 token 失败 → 回登录页报错",
              r.status_code == 302 and "auth_error" in r.headers["location"],
              r.headers.get("location", ""))
        TOKEN_OK = True

        print("=== 5. 完整登录：首次自动建号 ===")
        c = httpx.Client(base_url=base, timeout=20)
        r0 = c.get("/api/auth/gitcode/start", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        r = c.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        check("回调后 302 回 /app", r.status_code == 302 and r.headers["location"] == "/app",
              f"{r.status_code} {r.headers.get('location')}")
        check("拿到了会话 cookie", "ml_session" in c.cookies, str(dict(c.cookies)))
        me = c.get("/api/me").json()
        check("已登录", me["user"]["username"] == "gc-user", str(me["user"]))
        check("昵称取自 GitCode", me["user"]["display_name"] == "示例用户", str(me["user"]))
        check("标记为已绑定", me["user"]["gitcode_bound"] is True)
        check("纯 GitCode 账号没有密码", me["user"]["has_password"] is False)
        check("state cookie 已清掉", "ml_oauth" not in c.cookies)

        print("=== 6. 再次登录：复用同一个账号，不重复建 ===")
        c2 = httpx.Client(base_url=base, timeout=20)
        r0 = c2.get("/api/auth/gitcode/start", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        c2.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        me2 = c2.get("/api/me").json()
        check("还是同一个用户", me2["user"]["id"] == me["user"]["id"],
              f"{me2['user']['id']} vs {me['user']['id']}")

        print("=== 7. 用户名冲突时自动让路 ===")
        clash = httpx.Client(base_url=base, timeout=20)
        clash.post("/api/auth/register", json={"username": "gc-user", "password": "pw123456"})
        # 上面会 409（已被 GitCode 建号的用户占了），换个名字占坑再让 GitCode 用户来
        clash.post("/api/auth/register", json={"username": "someone", "password": "pw123456"})
        PROFILE.update({"id": "ffffffffffffffffffffffff", "login": "someone",
                        "name": "重名的人"})
        c3 = httpx.Client(base_url=base, timeout=20)
        r0 = c3.get("/api/auth/gitcode/start", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        c3.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        me3 = c3.get("/api/me").json()
        check("自动改名而不是撞车", me3["user"]["username"] == "someone-2",
              str(me3["user"]))

        print("=== 8. 绑定已有账号 ===")
        PROFILE.update({"id": "111122223333444455556666", "login": "binder", "name": "绑定的"})
        pw_user = httpx.Client(base_url=base, timeout=20)
        pw_user.post("/api/auth/register", json={"username": "pw_user", "password": "pw123456"})
        if pw_user.get("/api/me").status_code != 200:
            pw_user.post("/api/auth/login", json={"username": "pw_user", "password": "pw123456"})
        check("绑定前未绑定", pw_user.get("/api/me").json()["user"]["gitcode_bound"] is False)

        r0 = pw_user.get("/api/auth/gitcode/start?purpose=bind", follow_redirects=False)
        check("绑定也走授权跳转", r0.status_code == 302, str(r0.status_code))
        check("cookie 记录 bind 用途和用户 id", "|bind|" in r0.cookies["ml_oauth"],
              r0.cookies["ml_oauth"])
        st = r0.cookies["ml_oauth"].split("|")[0]
        r = pw_user.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        check("绑定后 302 回设置页", r.headers.get("location", "").startswith("/app?bound=1"),
              r.headers.get("location", ""))
        me4 = pw_user.get("/api/me").json()
        check("已绑定", me4["user"]["gitcode_bound"] is True)
        check("原会话仍然有效（没有换账号）", me4["user"]["username"] == "pw_user", str(me4["user"]))
        check("这个账号有密码", me4["user"]["has_password"] is True)

        print("=== 9. 一个 GitCode 账号不能绑到两个本地账号 ===")
        other = httpx.Client(base_url=base, timeout=20)
        other.post("/api/auth/register", json={"username": "other_user", "password": "pw123456"})
        if other.get("/api/me").status_code != 200:
            other.post("/api/auth/login", json={"username": "other_user", "password": "pw123456"})
        r0 = other.get("/api/auth/gitcode/start?purpose=bind", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        r = other.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        # auth_error 是 URL 编码的，断言前先解码
        from urllib.parse import parse_qs, urlparse
        loc = r.headers.get("location", "")
        reason = parse_qs(urlparse(loc).query).get("auth_error", [""])[0]
        check("被拒绝并说明原因", "已经绑定了另一个账号" in reason, f"{loc} → {reason}")
        check("没有把绑定抢过去",
              other.get("/api/me").json()["user"]["gitcode_bound"] is False)

        print("=== 10. 未登录不能发起绑定 ===")
        r = anon.get("/api/auth/gitcode/start?purpose=bind", follow_redirects=False)
        check("401", r.status_code == 401, str(r.status_code))

        print("=== 11. 解绑 ===")
        r = pw_user.post("/api/auth/gitcode/unbind")
        check("有密码的账号可以解绑", r.status_code == 200, r.text[:120])
        check("解绑生效", pw_user.get("/api/me").json()["user"]["gitcode_bound"] is False)
        r = c.post("/api/auth/gitcode/unbind")
        check("纯 GitCode 账号不许解绑（否则锁死自己）", r.status_code == 400, r.text[:120])

        print("=== 12. 纯 GitCode 账号可以直接设置密码 ===")
        r = c.post("/api/me/password", json={"old_password": "", "new_password": "newpw123"})
        check("不用填旧密码就能设置", r.status_code == 200, r.text[:120])
        fresh = httpx.Client(base_url=base, timeout=20)
        r = fresh.post("/api/auth/login", json={"username": "gc-user", "password": "newpw123"})
        check("设完之后能用密码登录", r.status_code == 200, r.text[:120])
        check("且此时可以解绑了", c.post("/api/auth/gitcode/unbind").status_code == 200)

        print("=== 13. 假 token 取不到资料时也不能崩 ===")
        good_token = PROFILE
        PROFILE.update({"id": None})
        c4 = httpx.Client(base_url=base, timeout=20)
        r0 = c4.get("/api/auth/gitcode/start", follow_redirects=False)
        st = r0.cookies["ml_oauth"].split("|")[0]
        r = c4.get(f"/api/auth/gitcode/callback?code=x&state={st}", follow_redirects=False)
        check("资料缺 id → 回登录页报错", "auth_error" in r.headers.get("location", ""),
              r.headers.get("location", ""))
        PROFILE.update(good_token)

    finally:
        proc.kill()
        fake.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 46)
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
