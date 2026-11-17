from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .storage_events import EventStoreMixin
from .storage_registry import RegistryStoreMixin
from .storage_rolling import RollingDailyLogStore


class Store(RegistryStoreMixin, EventStoreMixin):
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.rolling_store = RollingDailyLogStore(self.db_path)

    def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
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

                create table if not exists incidents (
                    incident_id text primary key,
                    website_id text not null,
                    severity text not null,
                    status text not null,
                    title text not null,
                    started_at text not null,
                    last_seen_at text not null,
                    primary_agent_id text not null,
                    primary_role text not null,
                    fingerprints_json text not null,
                    affected_agents_json text not null,
                    event_count integer not null,
                    ai_summary text,
                    confidence real,
                    memory_status text not null
                );

                create index if not exists idx_incidents_website_status
                    on incidents (website_id, status, last_seen_at);

                create table if not exists agents (
                    agent_id text primary key,
                    website_id text,
                    agent_role text not null,
                    hostname text,
                    source_ip text,
                    status text not null,
                    agent_token text not null,
                    registered_at text not null,
                    last_seen_at text not null,
                    cluster_id text,
                    cpu_percent real,
                    ram_percent real,
                    disk_percent real,
                    maintenance_until text
                );

                create table if not exists websites (
                    website_id text primary key,
                    name text not null,
                    status text not null,
                    created_at text not null
                );

                create table if not exists clusters (
                    cluster_id text primary key,
                    website_id text not null,
                    name text not null,
                    cluster_type text not null,
                    quorum_min integer not null default 2,
                    status text not null default 'active',
                    description text not null default '',
                    created_at text not null
                );

                create index if not exists idx_clusters_website
                    on clusters (website_id);

                create table if not exists vm_relations (
                    relation_id text primary key,
                    website_id text not null,
                    source_id text not null,
                    target_id text not null,
                    relation_type text not null,
                    port integer,
                    protocol text not null default '',
                    is_manual integer not null default 1,
                    confidence real not null default 1.0,
                    last_seen_at text not null,
                    metadata_json text not null default '{}'
                );

                create index if not exists idx_vm_relations_website
                    on vm_relations (website_id);

                create table if not exists log_sources (
                    source_id text primary key,
                    website_id text not null,
                    agent_id text not null,
                    name text not null,
                    path text not null,
                    source_type text not null,
                    service text not null,
                    classification text not null,
                    confidence real not null,
                    status text not null,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    metadata_json text not null
                );

                create index if not exists idx_log_sources_website_agent
                    on log_sources (website_id, agent_id);
                create index if not exists idx_log_sources_status
                    on log_sources (website_id, status);

                create table if not exists topology_hints (
                    hint_id text primary key,
                    website_id text not null,
                    agent_id text not null,
                    source text not null,
                    hint_type text not null,
                    target text not null,
                    confidence real not null,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    metadata_json text not null
                );

                create index if not exists idx_topology_hints_website_agent
                    on topology_hints (website_id, agent_id);
                create index if not exists idx_topology_hints_target
                    on topology_hints (website_id, target);

                create table if not exists incident_memory (
                    memory_id text primary key,
                    website_id text not null,
                    fingerprint text not null,
                    category text not null,
                    root_cause text not null,
                    suggested_action text not null,
                    first_seen_at text not null,
                    last_seen_at text not null,
                    seen_count integer not null,
                    confidence real not null
                );

                create index if not exists idx_incident_memory_lookup
                    on incident_memory (website_id, fingerprint, seen_count);

                create table if not exists suppressed_fingerprints (
                    website_id text not null,
                    fingerprint text not null,
                    reason text not null default 'false_positive',
                    created_at text not null,
                    primary key (website_id, fingerprint)
                );
                """
            )
            self._ensure_column(db, "agents", "website_id", "text")
            self._ensure_column(db, "agents", "machine_id", "text")
            self._ensure_column(db, "agents", "cluster_id", "text")
            self._ensure_column(db, "agents", "cpu_percent", "real")
            self._ensure_column(db, "agents", "ram_percent", "real")
            self._ensure_column(db, "agents", "disk_percent", "real")
            self._ensure_column(db, "agents", "maintenance_until", "text")
            db.execute(
                "create unique index if not exists idx_agents_machine_id "
                "on agents (machine_id) where machine_id is not null and machine_id != ''"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL;")
        db.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _ensure_column(self, db: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
        columns = {row["name"] for row in db.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            db.execute(f"alter table {table} add column {column} {ddl_type}")

    def purge_old_daily_dbs(
        self,
        retention_days: int = 14,
        reference_date: datetime | None = None,
    ) -> list[str]:
        return self.rolling_store.purge_old_daily_dbs(
            retention_days=retention_days,
            reference_date=reference_date,
        )

    def list_daily_db_files(self) -> list[dict[str, Any]]:
        return self.rolling_store.list_daily_db_files()

    def _insert_event(self, db: sqlite3.Connection, event: dict[str, Any]) -> None:
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

    def _find_recent_source_duplicate(
        self,
        db: sqlite3.Connection,
        event: dict[str, Any],
        window_seconds: int = 30,
    ) -> sqlite3.Row | None:
        source_id = str(event.get("source_id") or "").strip()
        if not source_id:
            return None
        observed_at = _parse_iso(event.get("observed_at"))
        if not observed_at:
            return None
        cutoff = (observed_at - timedelta(seconds=window_seconds)).isoformat()
        return db.execute(
            """
            select event_id, incident_id
            from events
            where website_id = ?
                and agent_id = ?
                and normalized_message = ?
                and json_extract(metadata_json, '$.source_id') = ?
                and observed_at >= ?
            order by observed_at desc
            limit 1
            """,
            (
                event["website_id"],
                event["agent_id"],
                event["normalized_message"],
                source_id,
                cutoff,
            ),
        ).fetchone()

    def _upsert_incident(self, db: sqlite3.Connection, event: dict[str, Any]) -> str:
        existing = db.execute(
            """
            select i.*
            from incidents i
            where i.website_id = ? and i.status = 'open'
                and exists (
                    select 1
                    from json_each(i.fingerprints_json)
                    where json_each.value = ?
                )
            order by last_seen_at desc
            limit 1
            """,
            (event["website_id"], event["fingerprint"]),
        ).fetchone()

        if existing:
            incident = self._incident_row_to_dict(existing)
            fingerprints = sorted(set(incident["fingerprints"] + [event["fingerprint"]]))
            affected_agents = sorted(set(incident["affected_agents"] + [event["agent_id"]]))
            severity = _max_severity(incident["severity"], event["severity"])
            db.execute(
                """
                update incidents
                set severity = ?, last_seen_at = ?, fingerprints_json = ?,
                    affected_agents_json = ?, event_count = event_count + 1
                where incident_id = ?
                """,
                (
                    severity,
                    event["timestamp"],
                    json.dumps(fingerprints),
                    json.dumps(affected_agents),
                    incident["incident_id"],
                ),
            )
            return incident["incident_id"]

        incident_id = "inc_" + event["event_id"][4:]
        title = f"{event['website_id']} {event['category']} on {event['agent_id']}"
        ai_summary = event.get("ai_summary")
        confidence = event.get("confidence")
        db.execute(
            """
            insert into incidents (
                incident_id, website_id, severity, status, title, started_at,
                last_seen_at, primary_agent_id, primary_role, fingerprints_json,
                affected_agents_json, event_count, ai_summary, confidence,
                memory_status
            ) values (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 'suggested')
            """,
            (
                incident_id,
                event["website_id"],
                event["severity"],
                title,
                event["timestamp"],
                event["timestamp"],
                event["agent_id"],
                event["agent_role"],
                json.dumps([event["fingerprint"]]),
                json.dumps([event["agent_id"]]),
                ai_summary,
                confidence,
            ),
        )
        return incident_id

    def update_incident_ai_summary(
        self,
        website_id: str,
        ai_summary: str,
        confidence: float | None = None,
        incident_id: str | None = None,
    ) -> None:
        with self._connect() as db:
            if incident_id:
                db.execute(
                    "update incidents set ai_summary = ?, confidence = coalesce(?, confidence) where incident_id = ?",
                    (ai_summary, confidence, incident_id),
                )
            else:
                db.execute(
                    "update incidents set ai_summary = ?, confidence = coalesce(?, confidence) where website_id = ? and status = 'open'",
                    (ai_summary, confidence, website_id),
                )

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        metadata = json.loads(data.pop("metadata_json") or "{}")
        data["metadata"] = metadata
        for key in (
            "source_id",
            "source_confidence",
            "timestamp_confidence",
            "event_uid",
            "multiline",
            "line_count",
        ):
            if key in metadata:
                data[key] = metadata[key]
        return data

    def _log_source_by_id(self, source_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "select * from log_sources where source_id = ?",
                (source_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"log source not found: {source_id}")
        return self._log_source_row_to_dict(row)

    def _log_source_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def _topology_hint_by_id(self, hint_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "select * from topology_hints where hint_id = ?",
                (hint_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"topology hint not found: {hint_id}")
        return self._topology_hint_row_to_dict(row)

    def _topology_hint_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def _vm_relation_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["is_manual"] = bool(data.get("is_manual", 1))
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        return data

    def _incident_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["fingerprints"] = json.loads(data.pop("fingerprints_json"))
        data["affected_agents"] = json.loads(data.pop("affected_agents_json"))
        return data


def _max_severity(left: str, right: str) -> str:
    order = {"normal": 0, "warning": 1, "problem": 2, "critical": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
