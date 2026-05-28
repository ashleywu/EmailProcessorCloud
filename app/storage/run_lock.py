from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.storage.db import open_initialized

DEFAULT_LOCK_NAME = "daily_digest_agent"
DEFAULT_TTL_MINUTES = 60


def _process_alive(pid: int) -> bool:
    """Return True iff ``pid`` can receive signals on this POSIX host (cheap liveness probe)."""

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunLock:
    """Advisory lock stored in `run_locks`; expired rows may be stolen.

    Only the process instance that successfully called ``acquire`` may
    release the lock. ``release`` is a no-op if this instance never acquired
    or if the row no longer matches the lock token acquired here (e.g.
    stolen after TTL).

    Calling ``release`` without a prior successful ``acquire`` must not delete
    another holder's active lock row.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        lock_name: str = DEFAULT_LOCK_NAME,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> None:
        self._conn = open_initialized(db_path)
        self._lock_name = lock_name
        self._ttl_minutes = ttl_minutes
        self._lock_token_locked_at: str | None = None

    @property
    def lock_name(self) -> str:
        return self._lock_name

    def close(self) -> None:
        self._conn.close()

    def acquire(self, owner: str | None = None) -> bool:
        """Return True if lock acquired; False if an active (non-expired) lock exists."""

        self._lock_token_locked_at = None
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT expires_at, locked_at, owner
                FROM run_locks
                WHERE lock_name = ?
                """,
                (self._lock_name,),
            ).fetchone()
            now = datetime.now(timezone.utc)
            if row is not None:
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
                stale_by_dead_pid = False
                ow = row["owner"]
                if ow is not None:
                    txt = str(ow).strip()
                    if txt.isdigit():
                        stale_by_dead_pid = not _process_alive(int(txt))

                if expires_at > now and not stale_by_dead_pid:
                    conn.rollback()
                    return False

            locked_owner = owner if owner is not None else str(os.getpid())
            locked_at = now
            expires_at = locked_at + timedelta(minutes=self._ttl_minutes)
            locked_iso = locked_at.isoformat()
            conn.execute(
                """
                INSERT INTO run_locks (lock_name, locked_at, expires_at, owner)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(lock_name) DO UPDATE SET
                  locked_at = excluded.locked_at,
                  expires_at = excluded.expires_at,
                  owner = excluded.owner
                """,
                (
                    self._lock_name,
                    locked_iso,
                    expires_at.isoformat(),
                    locked_owner,
                ),
            )
            conn.commit()
            self._lock_token_locked_at = locked_iso
            return True
        except Exception:
            conn.rollback()
            self._lock_token_locked_at = None
            raise

    def release(self) -> None:
        """Remove the lock row only if this instance holds it."""

        token = self._lock_token_locked_at
        self._lock_token_locked_at = None
        if token is None:
            return
        row = self._conn.execute(
            "SELECT locked_at FROM run_locks WHERE lock_name = ?",
            (self._lock_name,),
        ).fetchone()
        if row is None:
            return
        if str(row["locked_at"]) != token:
            return
        self._conn.execute(
            "DELETE FROM run_locks WHERE lock_name = ? AND locked_at = ?",
            (self._lock_name, token),
        )
        self._conn.commit()
