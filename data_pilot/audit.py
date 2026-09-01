from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any


def utc_now() -> str:
    """Return a timezone-aware timestamp suitable for audit records."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    created_at: str
    question: str
    source: str
    model: str
    status: str
    duration_seconds: float
    row_count: int
    column_count: int
    fallback_used: bool
    sql: str = ""
    warnings: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


class AuditStore:
    """Small append-only SQLite audit store for local and single-node deployments."""

    def __init__(self, path: str | Path = ".datapilot/audit.db") -> None:
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self._lock = RLock()
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(path), check_same_thread=False, timeout=5.0
        )
        self._connection.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                question TEXT NOT NULL,
                source TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                row_count INTEGER NOT NULL,
                column_count INTEGER NOT NULL,
                fallback_used INTEGER NOT NULL,
                sql TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                error TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def append(self, record: RunRecord) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO analysis_runs (
                    run_id, created_at, question, source, model, status,
                    duration_seconds, row_count, column_count, fallback_used,
                    sql, warnings_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.created_at,
                    record.question,
                    record.source,
                    record.model,
                    record.status,
                    record.duration_seconds,
                    record.row_count,
                    record.column_count,
                    int(record.fallback_used),
                    record.sql,
                    json.dumps(record.warnings, ensure_ascii=False),
                    record.error,
                ),
            )
            self._connection.commit()

    def recent(self, limit: int = 20) -> list[RunRecord]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT run_id, created_at, question, source, model, status,
                       duration_seconds, row_count, column_count, fallback_used,
                       sql, warnings_json, error
                FROM analysis_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT run_id, created_at, question, source, model, status,
                       duration_seconds, row_count, column_count, fallback_used,
                       sql, warnings_json, error
                FROM analysis_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    @staticmethod
    def _row_to_record(row: tuple[Any, ...]) -> RunRecord:
        return RunRecord(
            run_id=row[0],
            created_at=row[1],
            question=row[2],
            source=row[3],
            model=row[4],
            status=row[5],
            duration_seconds=float(row[6]),
            row_count=int(row[7]),
            column_count=int(row[8]),
            fallback_used=bool(row[9]),
            sql=row[10],
            warnings=tuple(json.loads(row[11] or "[]")),
            error=row[12],
        )

    def close(self) -> None:
        self._connection.close()
