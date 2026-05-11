from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  subject TEXT,
  body_preview TEXT,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  received_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);

CREATE TABLE IF NOT EXISTS agent_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_outputs_email ON agent_outputs(email_id);

CREATE TABLE IF NOT EXISTS digests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL,
  title TEXT,
  body_html TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digest_emails (
  digest_id INTEGER NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  PRIMARY KEY (digest_id, email_id)
);

CREATE INDEX IF NOT EXISTS idx_digest_emails_email ON digest_emails(email_id);

CREATE TABLE IF NOT EXISTS run_locks (
  lock_name TEXT PRIMARY KEY,
  locked_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  owner TEXT
);
"""


def _migrate_legacy_digest_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='digests'",
    )
    if cur.fetchone() is None:
        return
    info = conn.execute("PRAGMA table_info(digests)").fetchall()
    col_names = {str(row[1]) for row in info}
    if "body_markdown" in col_names and "body_html" not in col_names:
        conn.execute("ALTER TABLE digests RENAME COLUMN body_markdown TO body_html")
        col_names.discard("body_markdown")
        col_names.add("body_html")
    if "body_html" not in col_names:
        conn.execute("ALTER TABLE digests ADD COLUMN body_html TEXT")
        col_names.add("body_html")
    if "error_message" not in col_names:
        conn.execute("ALTER TABLE digests ADD COLUMN error_message TEXT")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _migrate_legacy_digest_columns(conn)
    conn.commit()


def open_initialized(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    return conn
