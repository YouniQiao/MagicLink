"""运行时配置。

优先从环境变量读；同时支持项目根目录的 `.env`（不引第三方依赖，自己解析）。
这样无论是 ./run.sh、systemd 还是命令行直接起，配置行为都一致。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

AUTHORIZE_URL = "https://gitcode.com/oauth/authorize"
TOKEN_URL = "https://gitcode.com/oauth/token"
USER_API = "https://api.gitcode.com/api/v5/user"
# 只申请读用户资料这一个权限，够登录用
DEFAULT_SCOPE = "user_info"

_loaded = False


def _load_env_file() -> None:
    """把 .env 里的键值塞进 os.environ（不覆盖已有的环境变量）。

    只做最朴素的 `KEY=VALUE` 解析，支持 # 注释和简单的引号包裹。
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not ENV_FILE.exists():
        return
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str = "") -> str:
    _load_env_file()
    return os.environ.get(name, default).strip()


# ── GitCode OAuth ───────────────────────────────────────────────────────────

def authorize_url() -> str:
    """下面三个地址都允许用环境变量覆盖：私有部署和测试打桩都需要。"""
    return env("GITCODE_AUTHORIZE_URL") or AUTHORIZE_URL


def token_url() -> str:
    return env("GITCODE_TOKEN_URL") or TOKEN_URL


def user_api() -> str:
    return env("GITCODE_USER_API") or USER_API


def gitcode_client() -> tuple[str, str]:
    _load_env_file()
    return (os.environ.get("GITCODE_CLIENT_ID", "").strip(),
            os.environ.get("GITCODE_CLIENT_SECRET", "").strip())


def gitcode_enabled() -> bool:
    """两个凭据都配了才算开启；没配就不显示 GitCode 登录入口。"""
    cid, secret = gitcode_client()
    return bool(cid and secret)


def base_url_from(request) -> str:
    """拼回调地址用的站点根地址。

    优先级：MAGICLINK_BASE_URL > 请求本身的 base_url。
    部署在反向代理后面时，请显式设置 MAGICLINK_BASE_URL（例如 https://example.com），
    否则 uvicorn 未必能推断出对外协议和域名。
    """
    override = env("MAGICLINK_BASE_URL").rstrip("/")
    if override:
        return override
    return str(request.base_url).rstrip("/")


def gitcode_redirect_uri(request) -> str:
    explicit = env("GITCODE_REDIRECT_URI")
    if explicit:
        return explicit
    return base_url_from(request) + "/api/auth/gitcode/callback"


def http_client_kwargs(timeout: float = 8.0) -> dict:
    """httpx 客户端参数（抓取链接元信息、调 GitCode 都用它）。

    默认 trust_env=False：macOS 的「系统代理设置」常指向没启动的 Clash，
    httpx 一旦采信就会以一个看不懂的 SSL 错误失败，而此时直连其实是通的。
    确实要走代理时显式设 MAGICLINK_PROXY。
    """
    _load_env_file()
    kw: dict = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {"User-Agent": f"MagicLink/1.0 (+{env('MAGICLINK_BASE_URL') or 'local'})"},
    }
    proxy = os.environ.get("MAGICLINK_PROXY", "").strip()
    if proxy:
        kw["proxy"] = proxy
    else:
        kw["trust_env"] = False
    return kw
