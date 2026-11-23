"""认证与密钥：PBKDF2 密码、HS256 JWT（标准库实现）、Fernet 敏感配置加密。

设计取舍：不引入 python-jose/passlib，减少部署依赖；
令牌内部用户与门户令牌用 scope 严格隔离。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PBKDF2_ROUNDS = 180_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, salt: bytes = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(rounds))
        return hmac.compare_digest(_b64(calc), digest)
    except Exception:
        return False


def get_secret() -> str:
    key = os.getenv("SECRET_KEY")
    if key and key != "CHANGE_ME_TO_A_LONG_RANDOM_STRING":
        return key
    keyfile = DATA_DIR / "secret.key"
    if not keyfile.exists():
        keyfile.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return keyfile.read_text(encoding="utf-8").strip()


def _fernet():
    from cryptography.fernet import Fernet
    key = os.getenv("MASTER_KEY")
    if not key:
        keyfile = DATA_DIR / "master.key"
        if not keyfile.exists():
            keyfile.write_bytes(Fernet.generate_key())
        key = keyfile.read_bytes()
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_value(plain: str) -> str:
    if plain is None or plain == "":
        return ""
    return "enc:" + _fernet().encrypt(str(plain).encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    if not value:
        return ""
    if not str(value).startswith("enc:"):
        return value  # 兼容历史明文
    try:
        return _fernet().decrypt(str(value)[4:].encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def make_token(payload: dict, ttl_days: int = 30) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_days * 86400
    body["iat"] = int(time.time())
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    data = _b64(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _b64(hmac.new(get_secret().encode(), f"{head}.{data}".encode(), hashlib.sha256).digest())
    return f"{head}.{data}.{sig}"


def parse_token(token: str) -> dict:
    try:
        head, data, sig = token.split(".")
        expect = _b64(hmac.new(get_secret().encode(), f"{head}.{data}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return {}
        body = json.loads(_unb64(data))
        if body.get("exp", 0) < int(time.time()):
            return {}
        return body
    except Exception:
        return {}


def is_locked(locked_until) -> bool:
    return bool(locked_until and locked_until > datetime.utcnow())


def lock_until(minutes: int = 15):
    return datetime.utcnow() + timedelta(minutes=minutes)
