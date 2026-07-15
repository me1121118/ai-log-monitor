from __future__ import annotations

import json
import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


INCIDENT_SEVERITIES = {"problem", "critical"}


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

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
                    last_seen_at text not null
                );

                create table if not exists websites (
                    website_id text primary key,
                    name text not null,
                    status text not null,
                    created_at text not null
                );

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
                """
            )
            self._ensure_column(db, "agents", "website_id", "text")

    def register_agent(self, agent: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(agent.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("missing required agent field: agent_id")
        agent_role = str(agent.get("agent_role") or agent.get("role") or "unknown")
        registered_at = str(agent.get("registered_at") or "")
        if not registered_at:
            raise ValueError("missing required agent field: registered_at")
        token = "agt_" + agent_id + "_" + str(abs(hash((agent_id, registered_at))))[:16]
        incoming_website_id = str(agent.get("website_id") or "").strip() or None
        final_website_id = incoming_website_id

        with self._connect() as db:
            existing = db.execute(
                "select agent_token, website_id from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
            if existing:
                token = str(existing["agent_token"])
                final_website_id = incoming_website_id or existing["website_id"]
                db.execute(
                    """
                    update agents
                    set website_id = coalesce(?, website_id), agent_role = ?, hostname = ?, source_ip = ?,
                        status = 'active', last_seen_at = ?
                    where agent_id = ?
                    """,
                    (
                        incoming_website_id,
                        agent_role,
                        agent.get("hostname"),
                        agent.get("source_ip"),
                        registered_at,
                        agent_id,
                    ),
                )
            else:
                db.execute(
                    """
                    insert into agents (
                        agent_id, website_id, agent_role, hostname, source_ip, status,
                        agent_token, registered_at, last_seen_at
                    ) values (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        agent_id,
                        incoming_website_id,
                        agent_role,
                        agent.get("hostname"),
                        agent.get("source_ip"),
                        token,
                        registered_at,
                        registered_at,
                    ),
                )
        return {
            "agent_id": agent_id,
            "website_id": final_website_id,
            "agent_role": agent_role,
            "agent_token": token,
            "status": "active",
        }

    def upsert_website(self, website: dict[str, Any]) -> dict[str, Any]:
        website_id = str(website.get("website_id") or "").strip()
        if not website_id:
            raise ValueError("missing required website field: website_id")
        name = str(website.get("name") or website_id)
        created_at = str(website.get("created_at") or "")
        if not created_at:
            raise ValueError("missing required website field: created_at")

        with self._connect() as db:
            db.execute(
                """
                insert into websites (website_id, name, status, created_at)
                values (?, ?, 'active', ?)
                on conflict(website_id) do update set
                    name = excluded.name,
                    status = 'active'
                """,
                (website_id, name, created_at),
            )
        return {"website_id": website_id, "name": name, "status": "active"}

    def list_websites(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "select * from websites order by website_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                select agent_id, website_id, agent_role, hostname, source_ip,
                    status, registered_at, last_seen_at
                from agents
                order by agent_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def assign_agent(self, assignment: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(assignment.get("agent_id") or "").strip()
        website_id = str(assignment.get("website_id") or "").strip()
        agent_role = str(assignment.get("agent_role") or assignment.get("role") or "").strip()
        if not agent_id:
            raise ValueError("missing required assignment field: agent_id")
        if not website_id:
            raise ValueError("missing required assignment field: website_id")

        with self._connect() as db:
            existing = db.execute(
                "select * from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
            if not existing:
                raise ValueError(f"agent not found: {agent_id}")
            final_role = agent_role or str(existing["agent_role"])
            db.execute(
                """
                update agents
                set website_id = ?, agent_role = ?
                where agent_id = ?
                """,
                (website_id, final_role, agent_id),
            )
        return {"agent_id": agent_id, "website_id": website_id, "agent_role": final_role}

    def ingest_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            incident_id = None
            if event["severity"] in INCIDENT_SEVERITIES:
                incident_id = self._upsert_incident(db, event)
                event = dict(event)
                event["incident_id"] = incident_id
            self._insert_event(db, event)
            return {"event_id": event["event_id"], "incident_id": incident_id}

    def list_incidents(self, website_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from incidents"
        params: list[Any] = []
        if website_id:
            query += " where website_id = ?"
            params.append(website_id)
        query += " order by last_seen_at desc"

        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._incident_row_to_dict(row) for row in rows]

    def close_incident(self, incident_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "select * from incidents where incident_id = ?",
                (incident_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"incident not found: {incident_id}")
            db.execute(
                "update incidents set status = 'closed' where incident_id = ?",
                (incident_id,),
            )
        incident = self._incident_row_to_dict(row)
        incident["status"] = "closed"
        return incident

    def website_context(self, website_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                select * from events
                where website_id = ?
                order by timestamp desc, observed_at desc
                limit ?
                """,
                (website_id, limit),
            ).fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    def count_events(self, website_id: str | None = None) -> int:
        query = "select count(*) as total from events"
        params: list[Any] = []
        if website_id:
            query += " where website_id = ?"
            params.append(website_id)
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return int(row["total"] if row else 0)

    def event_page(
        self,
        website_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "select * from events"
        params: list[Any] = []
        if website_id:
            query += " where website_id = ?"
            params.append(website_id)
        query += " order by timestamp desc, observed_at desc limit ? offset ?"
        params.extend([limit, offset])
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                select * from events
                order by observed_at desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    def validate_agent_token(self, agent_id: str, agent_token: str) -> bool:
        if not agent_id or not agent_token:
            return False
        with self._connect() as db:
            row = db.execute(
                "select agent_token from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
        return bool(row and str(row["agent_token"]) == str(agent_token))

    def purge_older_than(self, cutoff_iso: str) -> dict[str, int]:
        with self._connect() as db:
            event_cursor = db.execute(
                "delete from events where observed_at < ?",
                (cutoff_iso,),
            )
            incident_cursor = db.execute(
                "delete from incidents where last_seen_at < ?",
                (cutoff_iso,),
            )
            memory_cursor = db.execute(
                "delete from incident_memory where last_seen_at < ?",
                (cutoff_iso,),
            )
        return {
            "events": max(event_cursor.rowcount, 0),
            "incidents": max(incident_cursor.rowcount, 0),
            "memory": max(memory_cursor.rowcount, 0),
        }

    def match_incident_memory(
        self,
        website_id: str,
        fingerprints: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        clean_fingerprints = [str(value) for value in fingerprints if value]
        if not clean_fingerprints:
            return []
        placeholders = ",".join("?" for _ in clean_fingerprints)
        params: list[Any] = [website_id, *clean_fingerprints, limit]
        with self._connect() as db:
            rows = db.execute(
                f"""
                select *
                from incident_memory
                where website_id = ? and fingerprint in ({placeholders})
                order by seen_count desc, last_seen_at desc
                limit ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_incident_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        website_id = str(memory.get("website_id") or "").strip()
        fingerprint = str(memory.get("fingerprint") or "").strip()
        category = str(memory.get("category") or "unknown").strip() or "unknown"
        root_cause = str(memory.get("root_cause") or "").strip()
        suggested_action = str(memory.get("suggested_action") or "").strip()
        observed_at = str(memory.get("observed_at") or "")
        confidence = float(memory.get("confidence") or 0.0)
        if not website_id:
            raise ValueError("missing required memory field: website_id")
        if not fingerprint:
            raise ValueError("missing required memory field: fingerprint")
        if not root_cause:
            raise ValueError("missing required memory field: root_cause")
        if not suggested_action:
            raise ValueError("missing required memory field: suggested_action")
        if not observed_at:
            raise ValueError("missing required memory field: observed_at")

        memory_id = "mem_" + hashlib.sha1(f"{website_id}|{fingerprint}".encode("utf-8")).hexdigest()[:20]
        with self._connect() as db:
            db.execute(
                """
                insert into incident_memory (
                    memory_id, website_id, fingerprint, category, root_cause,
                    suggested_action, first_seen_at, last_seen_at, seen_count,
                    confidence
                ) values (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                on conflict(memory_id) do update set
                    category = excluded.category,
                    root_cause = excluded.root_cause,
                    suggested_action = excluded.suggested_action,
                    last_seen_at = excluded.last_seen_at,
                    seen_count = seen_count + 1,
                    confidence = excluded.confidence
                """,
                (
                    memory_id,
                    website_id,
                    fingerprint,
                    category,
                    root_cause,
                    suggested_action,
                    observed_at,
                    observed_at,
                    confidence,
                ),
            )
            row = db.execute(
                "select * from incident_memory where memory_id = ?",
                (memory_id,),
            ).fetchone()
        return dict(row)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _ensure_column(self, db: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
        columns = {row["name"] for row in db.execute(f"pragma table_info({table})").fetchall()}
        if column not in columns:
            db.execute(f"alter table {table} add column {column} {ddl_type}")

    def _insert_event(self, db: sqlite3.Connection, event: dict[str, Any]) -> None:
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
                json.dumps(event.get("metadata") or {}, sort_keys=True),
            ),
        )

    def _upsert_incident(self, db: sqlite3.Connection, event: dict[str, Any]) -> str:
        existing = db.execute(
            """
            select * from incidents
            where website_id = ? and status = 'open' and fingerprints_json like ?
            order by last_seen_at desc
            limit 1
            """,
            (event["website_id"], f"%{event['fingerprint']}%"),
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
        db.execute(
            """
            insert into incidents (
                incident_id, website_id, severity, status, title, started_at,
                last_seen_at, primary_agent_id, primary_role, fingerprints_json,
                affected_agents_json, event_count, ai_summary, confidence,
                memory_status
            ) values (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, 1, null, null, 'suggested')
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
            ),
        )
        return incident_id

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json"))
        return data

    def _incident_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["fingerprints"] = json.loads(data.pop("fingerprints_json"))
        data["affected_agents"] = json.loads(data.pop("affected_agents_json"))
        return data


def _max_severity(left: str, right: str) -> str:
    order = {"normal": 0, "warning": 1, "problem": 2, "critical": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right
