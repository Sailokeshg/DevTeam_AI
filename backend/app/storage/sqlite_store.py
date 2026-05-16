"""SQLite-backed storage for DevTeam AI run history."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas.agent_state import AgentState


@dataclass(slots=True)
class StoredRun:
    """A persisted workflow run record."""

    run_id: str
    repository_path: str
    feature_request: str
    status: str
    state: AgentState
    created_at: datetime
    updated_at: datetime


class RunNotFoundError(KeyError):
    """Raised when a requested run id is not present in storage."""


class SQLiteRunStore:
    """Small SQLite repository for synchronous workflow run records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_env(cls) -> SQLiteRunStore:
        """Create a store from DEVTEAM_AI_RUN_DB or a local project default."""
        configured_path = os.getenv("DEVTEAM_AI_RUN_DB")
        database_path = (
            Path(configured_path)
            if configured_path
            else Path.cwd() / ".devteam-ai" / "runs.sqlite3"
        )
        return cls(database_path)

    def create_run(self, *, repository_path: str, feature_request: str) -> StoredRun:
        """Create and persist a new run in running status."""
        now = _now_utc()
        run_id = uuid4().hex
        state = AgentState(
            user_request=feature_request,
            repository_path=repository_path,
            final_status="running",
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    repository_path,
                    feature_request,
                    status,
                    state_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    repository_path,
                    feature_request,
                    state.final_status,
                    state.model_dump_json(),
                    _serialize_datetime(now),
                    _serialize_datetime(now),
                ),
            )

        return StoredRun(
            run_id=run_id,
            repository_path=repository_path,
            feature_request=feature_request,
            status=state.final_status,
            state=state,
            created_at=now,
            updated_at=now,
        )

    def update_run_state(self, run_id: str, state: AgentState) -> StoredRun:
        """Persist the latest AgentState for an existing run."""
        existing = self.get_run(run_id)
        updated_at = _now_utc()

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, state_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    state.final_status,
                    state.model_dump_json(),
                    _serialize_datetime(updated_at),
                    run_id,
                ),
            )

        return StoredRun(
            run_id=run_id,
            repository_path=existing.repository_path,
            feature_request=existing.feature_request,
            status=state.final_status,
            state=state,
            created_at=existing.created_at,
            updated_at=updated_at,
        )

    def get_run(self, run_id: str) -> StoredRun:
        """Load a run by id."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    run_id,
                    repository_path,
                    feature_request,
                    status,
                    state_json,
                    created_at,
                    updated_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            raise RunNotFoundError(run_id)

        return _row_to_stored_run(row)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    repository_path TEXT NOT NULL,
                    feature_request TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _row_to_stored_run(row: sqlite3.Row) -> StoredRun:
    return StoredRun(
        run_id=str(row["run_id"]),
        repository_path=str(row["repository_path"]),
        feature_request=str(row["feature_request"]),
        status=str(row["status"]),
        state=AgentState.model_validate_json(str(row["state_json"])),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
    )


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _serialize_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
