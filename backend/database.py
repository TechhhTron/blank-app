from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import CREATE_AUTH_REQUESTS_SQL, CREATE_USERS_SQL
from .utils import expiry_for_plan, iso_now, plan_to_days

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = Path(os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "tradematic.sqlite3")))


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(CREATE_USERS_SQL)
        conn.execute(CREATE_AUTH_REQUESTS_SQL)
        conn.commit()
    seed_local_user()


def seed_local_user() -> None:
    if os.getenv("SEED_LOCAL_USER", "true").lower() not in {"1", "true", "yes"}:
        return

    from .auth import hash_password

    email = os.getenv("SEED_USER_EMAIL", "admin@example.com").strip().lower()
    password = os.getenv("SEED_USER_PASSWORD", "admin")
    full_name = os.getenv("SEED_USER_FULL_NAME", "Admin User")
    plan_name = os.getenv("SEED_USER_PLAN", "Monthly")
    now = iso_now()

    with get_connection() as conn:
        exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if exists:
            return
        conn.execute(
            """
            INSERT INTO users (
                full_name, email, password_hash, plan_name, subscription_days,
                subscription_expires_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                full_name,
                email,
                hash_password(password),
                plan_name,
                plan_to_days(plan_name),
                expiry_for_plan(plan_name),
                now,
                now,
            ),
        )
        conn.commit()


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    data = dict(user)
    data.pop("password_hash", None)
    data.pop("broker_secret_key", None)
    data["broker_connected"] = bool(data.get("broker_connected"))
    data["demo_used"] = bool(data.get("demo_used"))
    data["broker_secret_saved"] = bool(user.get("broker_secret_key"))
    data["broker_token_saved"] = bool(user.get("broker_session_token"))
    return data


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()
        return row_to_dict(row)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row_to_dict(row)


def update_user_fields(user_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    if not fields:
        user = get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        return user

    fields = dict(fields)
    fields["updated_at"] = iso_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [user_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", values)
        conn.commit()
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")
    return user


def create_broker_auth_request(user_id: int, state: str, redirect_uri: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO broker_auth_requests (user_id, state, redirect_uri, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, state, redirect_uri, iso_now()),
        )
        conn.commit()


def consume_broker_auth_request(state: str | None) -> dict[str, Any] | None:
    query = """
        SELECT * FROM broker_auth_requests
        WHERE used_at IS NULL
    """
    params: list[Any] = []
    if state:
        query += " AND state = ?"
        params.append(state)
    query += " ORDER BY created_at DESC LIMIT 1"

    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE broker_auth_requests SET used_at = ? WHERE id = ?",
            (iso_now(), row["id"]),
        )
        conn.commit()
        return row_to_dict(row)

