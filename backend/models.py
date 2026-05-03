USER_COLUMNS = (
    "id",
    "full_name",
    "email",
    "password_hash",
    "plan_name",
    "subscription_days",
    "subscription_expires_at",
    "capital",
    "index_name",
    "risk_mode",
    "broker_app_id",
    "broker_secret_key",
    "broker_client_id",
    "broker_auth_code",
    "broker_session_token",
    "broker_connected",
    "last_authorized_at",
    "payment_status",
    "payment_id",
    "demo_used",
    "created_at",
    "updated_at",
)


CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    plan_name TEXT NOT NULL DEFAULT 'Monthly',
    subscription_days INTEGER NOT NULL DEFAULT 30,
    subscription_expires_at TEXT,
    capital REAL NOT NULL DEFAULT 60000,
    index_name TEXT NOT NULL DEFAULT 'None',
    risk_mode TEXT NOT NULL DEFAULT 'Medium',
    broker_app_id TEXT,
    broker_secret_key TEXT,
    broker_client_id TEXT,
    broker_auth_code TEXT,
    broker_session_token TEXT,
    broker_connected INTEGER NOT NULL DEFAULT 0,
    last_authorized_at TEXT,
    payment_status TEXT NOT NULL DEFAULT 'active',
    payment_id TEXT,
    demo_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


CREATE_AUTH_REQUESTS_SQL = """
CREATE TABLE IF NOT EXISTS broker_auth_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

