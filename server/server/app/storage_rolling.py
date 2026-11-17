from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


DAILY_EVENTS_SCHEMA = """
create table if not exists events (
    event_id text primary key,
    website_id text not null,
    agent_id text not null,
    agent_role text not null,
    log_type text not null,
    service text not null,
    timestamp text not null,
    observed_at text not null,
    severity text not null,
    category text not null,
    status_code integer,
    message text not null,
    normalized_message text not null,
    fingerprint text not null,
    incident_id text,
    metadata_json text not null
);

create index if not exists idx_events_website_time
    on events (website_id, timestamp);
create index if not exists idx_events_incident
    on events (incident_id);
create index if not exists idx_events_fingerprint
    on events (website_id, fingerprint);
"""


def _extract_date_str(event: dict[str, Any]) -> str:
    for key in ("timestamp", "observed_at"):
        raw = str(event.get(key) or "").strip()
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            date_part = raw[:10]
            try:
                datetime.strptime(date_part, "%Y-%m-%d")
                return date_part
            except ValueError:
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class RollingDailyLogStore:
    def __init__(self, main_db_path: Path):
        self.main_db_path = Path(main_db_path)
        self.daily_dir = self.main_db_path.parent / "daily_logs"
        self._initialized_dbs: set[Path] = set()

    def daily_db_path(self, date_str: str) -> Path:
        return self.daily_dir / f"logs_{date_str}.db"

    @contextmanager
    def _connect_daily(self, date_str: str) -> Iterator[sqlite3.Connection]:
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.daily_db_path(date_str)
        need_init = db_path not in self._initialized_dbs or not db_path.exists()
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA synchronous=NORMAL;")
        try:
            if need_init:
                db.executescript(DAILY_EVENTS_SCHEMA)
                self._initialized_dbs.add(db_path)
            yield db
            db.commit()
        finally:
            db.close()

    def _insert_daily_event(self, db: sqlite3.Connection, event: dict[str, Any]) -> None:
        metadata = dict(event.get("metadata") or {})
        for key in (
            "source_id",
            "source_confidence",
            "timestamp_confidence",
            "event_uid",
            "multiline",
            "line_count",
        ):
            if event.get(key) is not None:
                metadata[key] = event.get(key)
        db.execute(
            """
            insert or ignore into events (
                event_id, website_id, agent_id, agent_role, log_type, service,
                timestamp, observed_at, severity, category, status_code, message,
                normalized_message, fingerprint, incident_id, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["website_id"],
                event["agent_id"],
                event["agent_role"],
                event["log_type"],
                event["service"],
                event["timestamp"],
                event["observed_at"],
                event["severity"],
                event["category"],
                event.get("status_code"),
                event["message"],
                event["normalized_message"],
                event["fingerprint"],
                event.get("incident_id"),
                json.dumps(metadata, sort_keys=True),
            ),
        )

    def write_event(self, event: dict[str, Any]) -> None:
        date_str = _extract_date_str(event)
        with self._connect_daily(date_str) as db:
            self._insert_daily_event(db, event)

    def write_events_batch(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            date_str = _extract_date_str(event)
            grouped.setdefault(date_str, []).append(event)
        for date_str, group in grouped.items():
            with self._connect_daily(date_str) as db:
                for event in group:
                    self._insert_daily_event(db, event)

    def list_daily_db_files(self) -> list[dict[str, Any]]:
        if not self.daily_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for path in sorted(self.daily_dir.glob("logs_*.db")):
            name = path.name
            if not (name.startswith("logs_") and name.endswith(".db")):
                continue
            date_part = name[len("logs_") : -len(".db")]
            try:
                size_bytes = path.stat().st_size
            except OSError:
                continue
            results.append(
                {
                    "filename": name,
                    "date": date_part,
                    "size_bytes": size_bytes,
                    "path": str(path),
                }
            )
        return results

    def purge_old_daily_dbs(
        self,
        retention_days: int = 1,
        reference_date: datetime | None = None,
    ) -> list[str]:
        if not self.daily_dir.exists():
            return []
        now = reference_date or datetime.now(timezone.utc)
        cutoff_date = (now - timedelta(days=max(int(retention_days), 0))).date()
        removed: list[str] = []
        for path in sorted(self.daily_dir.glob("logs_*.db")):
            name = path.name
            date_part = name[len("logs_") : -len(".db")]
            try:
                file_date = datetime.strptime(date_part, "%Y-%m-%d").date()
            except ValueError:
                continue
            if file_date < cutoff_date:
                try:
                    path.unlink(missing_ok=True)
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(path) + suffix)
                        sidecar.unlink(missing_ok=True)
                    self._initialized_dbs.discard(path)
                    removed.append(name)
                except OSError:
                    pass
        return removed
