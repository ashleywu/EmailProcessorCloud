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
  sender TEXT,
  body_preview TEXT,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  received_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);

CREATE TABLE IF NOT EXISTS email_sections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  section_key TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  heading TEXT,
  text TEXT NOT NULL,
  links_json TEXT NOT NULL,
  image_urls_json TEXT NOT NULL,
  content_hash TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(email_id, section_key)
);

CREATE INDEX IF NOT EXISTS idx_email_sections_email ON email_sections(email_id);

CREATE TABLE IF NOT EXISTS agent_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  email_section_id INTEGER NULL REFERENCES email_sections(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  category TEXT NULL,
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


def _migrate_emails_sender_column(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='emails'",
    )
    if cur.fetchone() is None:
        return
    col_names = {str(row[1]) for row in conn.execute("PRAGMA table_info(emails)").fetchall()}
    if "sender" not in col_names:
        conn.execute("ALTER TABLE emails ADD COLUMN sender TEXT")


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


def _migrate_email_sections_and_agent_outputs(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='emails'",
    )
    if cur.fetchone() is None:
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_sections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
          section_key TEXT NOT NULL,
          order_index INTEGER NOT NULL,
          heading TEXT,
          text TEXT NOT NULL,
          links_json TEXT NOT NULL,
          image_urls_json TEXT NOT NULL,
          content_hash TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          UNIQUE(email_id, section_key)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_email_sections_email
        ON email_sections(email_id)
        """
    )

    ao_cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_outputs'",
    )
    if ao_cur.fetchone() is None:
        return
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(agent_outputs)").fetchall()}
    if "email_section_id" not in cols:
        conn.execute(
            """
            ALTER TABLE agent_outputs
            ADD COLUMN email_section_id INTEGER NULL
              REFERENCES email_sections(id) ON DELETE CASCADE
            """
        )
        cols.add("email_section_id")
    if "category" not in cols:
        conn.execute("ALTER TABLE agent_outputs ADD COLUMN category TEXT")

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_outputs_email_section_kind
        ON agent_outputs(email_id, email_section_id, kind)
        """
    )


def _migrate_email_sections_content_hash(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='email_sections'",
    )
    if cur.fetchone() is None:
        return
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(email_sections)").fetchall()}
    if "content_hash" not in cols:
        conn.execute("ALTER TABLE email_sections ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _migrate_emails_sender_column(conn)
    _migrate_legacy_digest_columns(conn)
    _migrate_email_sections_and_agent_outputs(conn)
    _migrate_email_sections_content_hash(conn)
    conn.commit()


def open_initialized(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    return conn
