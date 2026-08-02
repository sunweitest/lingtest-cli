"""Small SQLite index for resumable sessions and retention."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lingtest.orchestration.event_adapter import _redact


class SessionStore:
    def __init__(self, path: str | Path, *, retention_days: int | None = 30):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lingtest_sessions (
                thread_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save(self, thread_id: str, state: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        safe_state = _redact(state)
        payload = json.dumps(safe_state, ensure_ascii=False, default=str)
        self.connection.execute(
            """
            INSERT INTO lingtest_sessions(thread_id, stage, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                stage=excluded.stage,
                state_json=excluded.state_json,
                updated_at=excluded.updated_at
            """,
            (thread_id, str(state.get("stage", "idle")), payload, now, now),
        )
        self.connection.commit()

    def load(self, thread_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT state_json FROM lingtest_sessions WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT thread_id, stage, created_at, updated_at FROM lingtest_sessions "
            "ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, thread_id: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM lingtest_sessions WHERE thread_id = ?", (thread_id,)
        )
        self._delete_checkpoints([thread_id])
        self.connection.commit()
        return cursor.rowcount > 0

    def prune(self, *, now: datetime | None = None, dry_run: bool = False) -> list[str]:
        if self.retention_days is None:
            return []
        if self.retention_days < 0:
            raise ValueError("retention_days must be zero, positive, or None for forever")
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        rows = self.connection.execute(
            "SELECT thread_id FROM lingtest_sessions WHERE updated_at < ?", (cutoff.isoformat(),)
        ).fetchall()
        ids = [str(row["thread_id"]) for row in rows]
        if ids and not dry_run:
            self.connection.executemany(
                "DELETE FROM lingtest_sessions WHERE thread_id = ?", [(item,) for item in ids]
            )
            self._delete_checkpoints(ids)
            self.connection.commit()
        return ids

    def _delete_checkpoints(self, thread_ids: list[str]) -> None:
        tables = {
            str(row["name"])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            if table in tables:
                self.connection.executemany(
                    f"DELETE FROM {table} WHERE thread_id = ?",
                    [(item,) for item in thread_ids],
                )

    def close(self) -> None:
        self.connection.close()
