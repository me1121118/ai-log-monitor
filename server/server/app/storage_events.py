from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

INCIDENT_SEVERITIES = {"problem", "critical"}


class EventStoreMixin:
    def _ingest_single_event_in_tx(
        self,
        db: sqlite3.Connection,
        event: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        existing = db.execute(
            "select incident_id from events where event_id = ?",
            (event["event_id"],),
        ).fetchone()
        if existing:
            return (
                {
                    "event_id": event["event_id"],
                    "incident_id": existing["incident_id"],
                    "stored": False,
                },
                None,
            )

        duplicate = self._find_recent_source_duplicate(db, event)
        if duplicate:
            return (
                {
                    "event_id": duplicate["event_id"],
                    "incident_id": duplicate["incident_id"],
                    "stored": False,
                    "duplicate_of": duplicate["event_id"],
                },
                None,
            )

        incident_id = None
        stored_event = dict(event)
        is_suppressed = False
        if stored_event.get("fingerprint"):
            sup_row = db.execute(
                "select 1 from suppressed_fingerprints where website_id = ? and fingerprint = ?",
                (stored_event["website_id"], stored_event["fingerprint"]),
            ).fetchone()
            is_suppressed = bool(sup_row)
        if stored_event["severity"] in INCIDENT_SEVERITIES and not is_suppressed:
            incident_id = self._upsert_incident(db, stored_event)
            stored_event["incident_id"] = incident_id
        elif is_suppressed:
            stored_event["severity"] = "normal"
        self._insert_event(db, stored_event)
        return (
            {
                "event_id": stored_event["event_id"],
                "incident_id": incident_id,
                "stored": True,
            },
            stored_event,
        )

    def ingest_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            result, stored_event = self._ingest_single_event_in_tx(db, event)
        if stored_event is not None and hasattr(self, "rolling_store"):
            self.rolling_store.write_event(stored_event)
        return result

    def ingest_events_batch(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        results: list[dict[str, Any]] = []
        stored_events: list[dict[str, Any]] = []
        with self._connect() as db:
            for event in events:
                result, stored_event = self._ingest_single_event_in_tx(db, event)
                results.append(result)
                if stored_event is not None:
                    stored_events.append(stored_event)
        if stored_events and hasattr(self, "rolling_store"):
            self.rolling_store.write_events_batch(stored_events)
        return results

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

    def suppress_incident(self, incident_id: str = "", website_id: str = "", title: str = "") -> dict[str, Any]:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            rows = []
            if incident_id:
                row = db.execute("select * from incidents where incident_id = ?", (incident_id,)).fetchone()
                if row:
                    rows.append(row)
            if not rows and website_id and title:
                rows = db.execute(
                    "select * from incidents where website_id = ? and title = ?",
                    (website_id, title),
                ).fetchall()
            if not rows:
                return {"suppressed": False, "incident_id": incident_id}
            suppressed_fps: list[str] = []
            for r in rows:
                inc = self._incident_row_to_dict(r)
                db.execute(
                    "update incidents set status = 'false_positive' where incident_id = ?",
                    (inc["incident_id"],),
                )
                for fp in inc.get("fingerprints") or []:
                    if fp:
                        suppressed_fps.append(fp)
                        db.execute(
                            "insert or replace into suppressed_fingerprints (website_id, fingerprint, reason, created_at) values (?, ?, 'false_positive', ?)",
                            (inc["website_id"], fp, now_iso),
                        )
            if website_id and title:
                db.execute(
                    "update incidents set status = 'false_positive' where website_id = ? and title = ?",
                    (website_id, title),
                )
        return {
            "suppressed": True,
            "incident_id": incident_id,
            "website_id": website_id,
            "title": title,
            "fingerprints": sorted(set(suppressed_fps)),
        }

    def website_context(
        self,
        website_id: str,
        limit: int = 100,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [website_id]
        since_clause = ""
        if since:
            since_clause = "and timestamp >= ?"
            params.append(since)
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(
                f"""
                select * from events
                where website_id = ?
                {since_clause}
                order by timestamp desc, observed_at desc
                limit ?
                """,
                params,
            ).fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    def count_events(
        self,
        website_id: str | None = None,
        agent_id: str | None = None,
        source_id: str | None = None,
    ) -> int:
        query = "select count(*) as total from events"
        clauses: list[str] = []
        params: list[Any] = []
        if website_id:
            clauses.append("website_id = ?")
            params.append(website_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if source_id:
            clauses.append("json_extract(metadata_json, '$.source_id') = ?")
            params.append(source_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return int(row["total"] if row else 0)

    def event_page(
        self,
        website_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
        agent_id: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "select * from events"
        clauses: list[str] = []
        params: list[Any] = []
        if website_id:
            clauses.append("website_id = ?")
            params.append(website_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if source_id:
            clauses.append("json_extract(metadata_json, '$.source_id') = ?")
            params.append(source_id)
        if clauses:
            query += " where " + " and ".join(clauses)
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
        return {
            "events": max(event_cursor.rowcount, 0),
            "incidents": 0,
            "memory": 0,
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
