"""Password hashing (stdlib scrypt) and token helpers — no extra deps."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1

# 纯 GitCode 登录建出来的账号没有密码，用这个哨兵值占位。
# verify_password 对它一定返回 False，所以不可能用密码登进来。
NO_PASSWORD = "!"
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N,
                        r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, expected_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(expected_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n),
                            r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_invite_code() -> str:
    """Short, human-shareable team invite code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous chars
    return "".join(secrets.choice(alphabet) for _ in range(10))
