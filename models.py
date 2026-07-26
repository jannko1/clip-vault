"""
SQLite database models for ClipVault.
Users, sessions, and eventually search/download history.
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "clipvault.db"

# On Vercel serverless, /var/task is read-only. Use /tmp instead.
if os.environ.get("VERCEL") or not os.access(str(DB_PATH.parent), os.W_OK):
    DB_PATH = Path("/tmp") / "clipvault.db"


def get_db():
    """Get a database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            searches_used INTEGER DEFAULT 0,
            search_month TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            last_login TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            media_type TEXT DEFAULT 'video',
            searched_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


# ── User operations ────────────────────────────────────

def create_user(email: str, password_hash: str, name: str = "") -> int | None:
    """Create a new user. Returns user_id or None if email exists."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name, created_at) VALUES (?, ?, ?, ?)",
            (email.strip().lower(), password_hash, name.strip(), now)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_user_by_email(email: str) -> dict | None:
    """Get user by email."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    """Get user by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_last_login(user_id: int):
    """Update last login timestamp."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
    conn.commit()
    conn.close()


# ── Session operations ─────────────────────────────────

def create_session(user_id: int, token: str, expires_hours: int = 168) -> str:
    """Create a session token. Default 7 days."""
    conn = get_db()
    now = datetime.now(timezone.utc)
    expires = now.replace(hour=now.hour + expires_hours).isoformat() if now.hour + expires_hours < 24 else now.isoformat()
    # Simple: always expire in 7 days
    from datetime import timedelta
    expires_at = (now + timedelta(hours=expires_hours)).isoformat()
    
    conn.execute(
        "INSERT INTO sessions (user_id, token, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (user_id, token, now.isoformat(), expires_at)
    )
    conn.commit()
    conn.close()
    return token


def get_session(token: str) -> dict | None:
    """Get session by token. Returns None if expired."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
        (token, now)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str):
    """Delete a session (logout)."""
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def delete_user_sessions(user_id: int):
    """Delete all sessions for a user."""
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ── Search tracking ────────────────────────────────────

def get_month_key():
    """Current month key like '2026-07'."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{str(now.month).zfill(2)}"


def get_searches_used(user_id: int) -> int:
    """Get searches used this month for a user."""
    conn = get_db()
    month = get_month_key()
    row = conn.execute(
        "SELECT searches_used, search_month FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return 0
    if row["search_month"] != month:
        return 0
    return row["searches_used"] or 0


def increment_searches(user_id: int):
    """Increment search counter for the month."""
    conn = get_db()
    month = get_month_key()
    user = conn.execute("SELECT searches_used, search_month FROM users WHERE id = ?", (user_id,)).fetchone()
    
    if not user or user["search_month"] != month:
        conn.execute(
            "UPDATE users SET searches_used = 1, search_month = ? WHERE id = ?",
            (month, user_id)
        )
    else:
        conn.execute(
            "UPDATE users SET searches_used = searches_used + 1 WHERE id = ?",
            (user_id,)
        )
    conn.commit()
    conn.close()


# ── Initialize on import ───────────────────────────────
# Lazy init — don't crash the app if DB isn't available yet
_init_done = False
def _lazy_init_db():
    global _init_done
    if _init_done:
        return
    try:
        init_db()
        _init_done = True
    except Exception as e:
        print(f"[WARNING] Database init skipped: {e}")

# Don't auto-init on import — let first request trigger it

