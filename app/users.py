"""User accounts, sessions, and persisted Amap keys (SQLite)."""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "users.db"
SESSION_TTL_SEC = 30 * 24 * 3600
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                amap_web_key TEXT NOT NULL DEFAULT '',
                amap_js_key TEXT NOT NULL DEFAULT '',
                amap_security_code TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    )
    return digest.hex()


def _mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def _user_public(row: sqlite3.Row, *, include_js_keys: bool = True) -> dict[str, Any]:
    web = (row["amap_web_key"] or "").strip()
    js = (row["amap_js_key"] or "").strip()
    sec = (row["amap_security_code"] or "").strip()
    data: dict[str, Any] = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "has_amap_keys": bool(web and js),
        "amap_web_key_masked": _mask_key(web),
        "amap_js_key_masked": _mask_key(js),
        "has_security_code": bool(sec),
    }
    if include_js_keys:
        data["amap_js_key"] = js
        data["amap_security_code"] = sec
    return data


def validate_username(username: str) -> Optional[str]:
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        return "用户名须为 3～32 位字母、数字或下划线"
    return None


def validate_password(password: str) -> Optional[str]:
    if not password or len(password) < 6:
        return "密码至少 6 位"
    if len(password) > 128:
        return "密码过长"
    return None


def register_user(username: str, password: str, display_name: str = "") -> dict[str, Any]:
    err = validate_username(username) or validate_password(password)
    if err:
        raise ValueError(err)
    username = username.strip()
    display_name = (display_name or username).strip()[:64]
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    now = time.time()
    try:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_salt, password_hash, display_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, salt, pwd_hash, display_name, now),
            )
            user_id = cur.lastrowid
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError:
        raise ValueError("用户名已被注册") from None
    if not row:
        raise RuntimeError("注册失败")
    return _user_public(row)


def authenticate(username: str, password: str) -> dict[str, Any]:
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("请输入用户名和密码")
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
    if not row:
        raise ValueError("用户名或密码错误")
    if _hash_password(password, row["password_salt"]) != row["password_hash"]:
        raise ValueError("用户名或密码错误")
    return _user_public(row)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_TTL_SEC
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires),
        )
    return token


def delete_session(token: str) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_session(token: Optional[str]) -> Optional[dict[str, Any]]:
    if not token:
        return None
    now = time.time()
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        row = conn.execute(
            """
            SELECT u.* FROM users u
            JOIN sessions s ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at >= ?
            """,
            (token, now),
        ).fetchone()
    if not row:
        return None
    return _user_public(row)


def get_user_keys(user_id: int) -> Optional[dict[str, str]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {
        "amap_web_key": (row["amap_web_key"] or "").strip(),
        "amap_js_key": (row["amap_js_key"] or "").strip(),
        "amap_security_code": (row["amap_security_code"] or "").strip(),
    }


def update_user_keys(
    user_id: int,
    amap_web_key: str,
    amap_js_key: str,
    amap_security_code: str = "",
    *,
    keep_web: bool = False,
    keep_js: bool = False,
    keep_security: bool = False,
) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise ValueError("用户不存在")

    web = (row["amap_web_key"] or "").strip() if keep_web else (amap_web_key or "").strip()
    js = (row["amap_js_key"] or "").strip() if keep_js else (amap_js_key or "").strip()
    if keep_security:
        sec = (row["amap_security_code"] or "").strip()
    else:
        sec = (amap_security_code or "").strip()

    if not web or not js:
        raise ValueError("请分别填写 Web 服务 Key 与 JS API Key")
    if web == js:
        raise ValueError("Web 服务 Key 与 JS API Key 不能相同")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET amap_web_key = ?, amap_js_key = ?, amap_security_code = ?
            WHERE id = ?
            """,
            (web, js, sec, user_id),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise ValueError("用户不存在")
    return _user_public(row)
