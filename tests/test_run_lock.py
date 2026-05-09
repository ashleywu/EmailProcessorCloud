from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.storage.run_lock import DEFAULT_LOCK_NAME, RunLock


def _expire_lock(db_path: Path) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE run_locks SET expires_at = ? WHERE lock_name = ?",
        (past, DEFAULT_LOCK_NAME),
    )
    conn.commit()
    conn.close()


def test_active_lock_prevents_second_acquire(tmp_path) -> None:
    db = tmp_path / "lock.db"
    lock1 = RunLock(db)
    assert lock1.acquire(owner="first") is True
    lock2 = RunLock(db)
    assert lock2.acquire(owner="second") is False
    lock1.release()
    assert lock2.acquire(owner="second") is True
    lock2.release()


def test_expired_lock_can_be_acquired(tmp_path) -> None:
    db = tmp_path / "lock2.db"
    lock = RunLock(db, ttl_minutes=60)
    assert lock.acquire(owner="a") is True
    _expire_lock(db)
    other = RunLock(db)
    assert other.acquire(owner="b") is True
    other.release()
