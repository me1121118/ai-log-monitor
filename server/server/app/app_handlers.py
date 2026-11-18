from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .analysis import build_ai_report, load_ai_settings, send_alert_notifications
from .app_common import parse_iso_datetime, severity_at_least
from .core import classify_event, normalize_event
from .notifications import send_recovery_notification
from .raw_archive import archive_event
from .utils import _safe_filename, _safe_path_part, _safe_timestamp


RETAINED_SEVERITIES = {"warning", "problem", "critical"}

class RequestHandlersMixin:
    def _ingest(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not self.store.validate_agent_token(
                str(payload.get("agent_id") or ""),
                normalized_headers.get("x-agent-token", ""),
            ):
                return self._json(401, {"error": "invalid agent token"})
        event = classify_event(normalize_event(payload))
        anomalies = self.traffic_detector.record_event(event) if hasattr(self, "traffic_detector") else []
        if event["severity"] == "normal":
            self.rolling_logs.append(event)
            response: dict[str, Any] = {
                "event_id": event["event_id"],
                "incident_id": None,
                "severity": event["severity"],
                "category": event["category"],
                "fingerprint": event["fingerprint"],
                "buffered": True,
            }
            if anomalies:
                response["traffic_anomalies"] = anomalies
            return self._json(202, response)
        return self._persist_retained_event(event, traffic_anomalies=anomalies)

    def _persist_retained_event(
        self,
        event: dict[str, Any],
        traffic_anomalies: list[dict[str, Any]] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        context_before = self.rolling_logs.context_for(event)
        if context_before:
            event = dict(event)
            event["metadata"] = dict(event.get("metadata") or {})
            event["metadata"]["context_before"] = context_before
        result = self.store.ingest_event(event)
        if result.get("stored"):
            archive_event(self.data_dir / "raw_logs", event)
        response: dict[str, Any] = {
            "event_id": result["event_id"],
            "incident_id": result["incident_id"],
            "severity": event["severity"],
            "category": event["category"],
            "fingerprint": event["fingerprint"],
            "buffered": False,
        }
        if traffic_anomalies:
            response["traffic_anomalies"] = traffic_anomalies
        auto_analysis = self._auto_analyze_if_needed(event)
        if auto_analysis:
            response["auto_analysis"] = auto_analysis
        return self._json(201, response)

    def _ingest_batch(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        raw_events = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(raw_events, list):
            raise ValueError("missing or invalid events list")
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            token = normalized_headers.get("x-agent-token", "")
            agent_ids = {
                str(item.get("agent_id") or (payload.get("agent_id") if isinstance(payload, dict) else "") or "")
                for item in raw_events
                if isinstance(item, dict)
            }
            for agent_id in agent_ids:
                if not self.store.validate_agent_token(agent_id, token):
                    return self._json(401, {"error": "invalid agent token"})

        retained_events: list[dict[str, Any]] = []
        retained_indices: list[int] = []
        results_list: list[dict[str, Any]] = []
        all_anomalies: list[dict[str, Any]] = []
        buffered_count = 0

        for item in raw_events:
            if not isinstance(item, dict):
                raise ValueError("each event in batch must be an object")
            event = classify_event(normalize_event(item))
            anomalies = self.traffic_detector.record_event(event) if hasattr(self, "traffic_detector") else []
            if anomalies:
                all_anomalies.extend(anomalies)
            if event["severity"] == "normal":
                self.rolling_logs.append(event)
                buffered_count += 1
                results_list.append(
                    {
                        "event_id": event["event_id"],
                        "incident_id": None,
                        "severity": event["severity"],
                        "category": event["category"],
                        "fingerprint": event["fingerprint"],
                        "buffered": True,
                    }
                )
            else:
                context_before = self.rolling_logs.context_for(event)
                if context_before:
                    event = dict(event)
                    event["metadata"] = dict(event.get("metadata") or {})
                    event["metadata"]["context_before"] = context_before
                retained_indices.append(len(results_list))
                results_list.append({})
                retained_events.append(event)

        stored_count = 0
        incident_ids: list[str] = []
        analyzed_websites: dict[str, dict[str, Any] | None] = {}
        if retained_events:
            batch_results = self.store.ingest_events_batch(retained_events)
            for idx, event, store_res in zip(retained_indices, retained_events, batch_results):
                if store_res.get("stored"):
                    archive_event(self.data_dir / "raw_logs", event)
                    stored_count += 1
                if store_res.get("incident_id"):
                    incident_ids.append(str(store_res["incident_id"]))
                entry: dict[str, Any] = {
                    "event_id": store_res["event_id"],
                    "incident_id": store_res["incident_id"],
                    "severity": event["severity"],
                    "category": event["category"],
                    "fingerprint": event["fingerprint"],
                    "buffered": False,
                }
                w_key = f"{event.get('website_id')}:{event.get('severity')}"
                if w_key not in analyzed_websites:
                    analyzed_websites[w_key] = self._auto_analyze_if_needed(event)
                auto_analysis = analyzed_websites[w_key]
                if auto_analysis:
                    entry["auto_analysis"] = auto_analysis
                results_list[idx] = entry

        response: dict[str, Any] = {
            "ingested": len(raw_events),
            "stored": stored_count,
            "buffered": buffered_count,
            "incident_ids": sorted(set(incident_ids)),
            "results": results_list,
        }
        if all_anomalies:
            response["traffic_anomalies"] = all_anomalies
        return self._json(201, response)

    def _internal_evidence(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        if not self._gateway_token_authorized(headers):
            return self._json(401, {"error": "invalid gateway token"})
        payload = json.loads(body.decode("utf-8"))
        event = normalize_event(payload)
        severity = str(event.get("severity") or "normal").lower()
        if severity not in RETAINED_SEVERITIES:
            return self._json(400, {"error": f"invalid severity: {severity}"})
        event = self._attach_gateway_classification(event, payload)
        return self._persist_retained_event(event)

    def _attach_gateway_classification(
        self,
        event: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event = dict(event)
        event["metadata"] = dict(event.get("metadata") or {})
        signal_type = str(payload.get("signal_type") or "").strip()
        if signal_type:
            event["signal_type"] = signal_type
            event["metadata"]["signal_type"] = signal_type
        if payload.get("classification") is not None:
            event["metadata"]["classification"] = payload["classification"]
        context_before = payload.get("context_before")
        if isinstance(context_before, list) and context_before:
            event["metadata"]["context_before"] = context_before
        return event

    def _gateway_token_authorized(self, headers: dict[str, str]) -> bool:
        if not self.gateway_internal_token:
            return False
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        candidate = str(normalized_headers.get("x-gateway-token", ""))
        return bool(candidate) and secrets.compare_digest(self.gateway_internal_token, candidate)

    def _internal_agent_validate(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        if not self._gateway_token_authorized(headers):
            return self._json(401, {"error": "invalid gateway token"})
        payload = json.loads(body.decode("utf-8"))
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("missing agent_id")
        if not self.enforce_agent_token:
            return self._json(200, {"valid": True, "enforced": False})
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        valid = self.store.validate_agent_token(agent_id, normalized_headers.get("x-agent-token", ""))
        return self._json(200, {"valid": bool(valid), "enforced": True})

    def _is_agent_in_maintenance(self, agent_id: str, now: datetime | None = None) -> bool:
        clean_id = str(agent_id or "").strip()
        if not clean_id:
            return False
        agents = self.store.list_agents()
        agent = next((a for a in agents if str(a.get("agent_id") or "") == clean_id), None)
        if not agent:
            return False
        maint_until = str(agent.get("maintenance_until") or "").strip()
        if not maint_until:
            return False
        maint_dt = parse_iso_datetime(maint_until)
        if not maint_dt:
            return False
        ref_now = now or datetime.now(timezone.utc)
        return maint_dt > ref_now

    def _auto_analyze_if_needed(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if self._is_agent_in_maintenance(str(event.get("agent_id") or "")):
            return None
        settings = load_ai_settings(self.ai_config_path)
        analysis_settings = settings.get("analysis", {})
        if not analysis_settings.get("auto_analyze", True):
            return None
        min_severity = str(analysis_settings.get("auto_analyze_min_severity") or "critical")
        if not severity_at_least(str(event.get("severity") or "normal"), min_severity):
            return None
        report = build_ai_report(self.store, str(event["website_id"]), settings=settings)
        notifications = send_alert_notifications(
            settings,
            event,
            report,
            http_post=self.notification_post,
        )
        return {
            "website_id": event["website_id"],
            "severity": event["severity"],
            "root_cause": report.get("root_cause"),
            "recommended_action": report.get("recommended_action"),
            "notifications": notifications,
        }

    def _register(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        if normalized_headers.get("x-enroll-token") != self.enroll_token:
            return self._json(401, {"error": "invalid enroll token"})
        payload = json.loads(body.decode("utf-8"))
        payload["registered_at"] = payload.get("registered_at") or datetime.now(timezone.utc).isoformat()
        website_id = str(payload.get("website_id") or "").strip()
        if website_id:
            payload["website_id"] = website_id
            self.store.upsert_website(
                {
                    "website_id": website_id,
                    "name": payload.get("website_name") or website_id,
                    "created_at": payload["registered_at"],
                }
            )
        return self._json(201, self.store.register_agent(payload))

    def _heartbeat(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        agent_id = str(payload.get("agent_id") or "").strip()
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not self.store.validate_agent_token(agent_id, normalized_headers.get("x-agent-token", "")):
                return self._json(401, {"error": "invalid agent token"})
        payload["observed_at"] = payload.get("observed_at") or datetime.now(timezone.utc).isoformat()

        existing_agent = next(
            (a for a in self.store.list_agents() if str(a.get("agent_id") or "") == agent_id),
            None,
        )
        was_stale_or_offline = False
        if existing_agent:
            prev_status = str(existing_agent.get("status") or "").lower()
            prev_seen_dt = parse_iso_datetime(str(existing_agent.get("last_seen_at") or ""))
            observed_dt = parse_iso_datetime(str(payload["observed_at"])) or datetime.now(timezone.utc)
            seconds_since_seen = (observed_dt - prev_seen_dt).total_seconds() if prev_seen_dt else None
            was_stale_or_offline = (
                prev_status in {"offline", "stale", "error", "down"}
                or (seconds_since_seen is not None and seconds_since_seen > 90)
            )

        updated = self.store.update_agent_heartbeat(payload)
        new_status = str(updated.get("status") or "active").lower()
        website_id = str(updated.get("website_id") or "").strip()

        # Proactive Disk % threshold alerting from heartbeat vitals
        try:
            disk_pct = float(updated.get("disk_percent") or 0.0)
            prev_disk_pct = float((existing_agent or {}).get("disk_percent") or 0.0)
            if website_id and disk_pct >= 85.0 and not self._is_agent_in_maintenance(agent_id):
                crossed_95 = disk_pct >= 95.0 and prev_disk_pct < 95.0
                crossed_85 = disk_pct >= 85.0 and prev_disk_pct < 85.0
                if crossed_95 or crossed_85:
                    sev = "critical" if disk_pct >= 95.0 else "warning"
                    msg = (
                        f"disk full: Disk usage critical at {disk_pct:.1f}% on {agent_id}"
                        if disk_pct >= 95.0
                        else f"warning: Disk usage high at {disk_pct:.1f}% on {agent_id}"
                    )
                    synth_ev = classify_event(
                        normalize_event(
                            {
                                "website_id": website_id,
                                "agent_id": agent_id,
                                "agent_role": str(updated.get("agent_role") or "app"),
                                "service": "system",
                                "log_type": "vitals_heartbeat",
                                "severity": sev,
                                "category": "disk_full",
                                "timestamp": str(payload["observed_at"]),
                                "message": msg,
                            }
                        )
                    )
                    synth_ev["category"] = "disk_full"
                    synth_ev["severity"] = sev
                    synth_ev["fingerprint"] = "fp_system_disk_full"
                    self._persist_retained_event(synth_ev)
        except Exception:
            pass

        if was_stale_or_offline and new_status in {"active", "online", "healthy"}:
            cluster_info: dict[str, Any] | None = None
            if website_id:
                try:
                    er_graph = self.store.build_er_topology_graph(website_id)
                    for cluster in er_graph.get("clusters") or []:
                        if agent_id in (cluster.get("member_ids") or []) or cluster.get("cluster_id") == updated.get("cluster_id"):
                            cluster_info = cluster
                            break
                except Exception:
                    cluster_info = None
            settings = load_ai_settings(self.ai_config_path)
            recovery_notifications = send_recovery_notification(
                settings,
                updated,
                cluster_info=cluster_info,
                http_post=self.notification_post,
            )
            updated["recovered"] = True
            if recovery_notifications:
                updated["recovery_notifications"] = recovery_notifications
        return self._json(200, updated)

    def _set_agent_maintenance(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("missing required agent field: agent_id")
        maintenance_until: str | None = None
        if "maintenance_until" in payload:
            val = payload.get("maintenance_until")
            maintenance_until = str(val).strip() if val else None
        elif payload.get("minutes") is not None:
            minutes = int(payload.get("minutes") or 0)
            if minutes > 0:
                maintenance_until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
            else:
                maintenance_until = None
        return self._json(200, self.store.set_agent_maintenance(agent_id, maintenance_until))

    def _upsert_cluster(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        cluster = self.store.upsert_cluster(payload)
        raw_members = payload.get("member_ids")
        if raw_members:
            if isinstance(raw_members, str):
                member_list = [m.strip() for m in raw_members.split(",") if m.strip()]
            elif isinstance(raw_members, list):
                member_list = [str(m).strip() for m in raw_members if str(m).strip()]
            else:
                member_list = []
            for aid in member_list:
                try:
                    self.store.assign_agent(
                        {
                            "agent_id": aid,
                            "website_id": cluster["website_id"],
                            "cluster_id": cluster["cluster_id"],
                        }
                    )
                except ValueError:
                    pass
        return self._json(201, cluster)

    def _upsert_relation(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        return self._json(201, self.store.upsert_vm_relation(payload))

    def _create_website(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        payload["created_at"] = payload.get("created_at") or datetime.now(timezone.utc).isoformat()
        return self._json(201, self.store.upsert_website(payload))

    def _assign_agent(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        return self._json(200, self.store.assign_agent(payload))

    def _upsert_log_sources(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        website_id = str(payload.get("website_id") or "").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        sources = list(payload.get("sources") or [])
        if not website_id:
            raise ValueError("missing website_id")
        if not agent_id:
            raise ValueError("missing agent_id")
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not self.store.validate_agent_token(agent_id, normalized_headers.get("x-agent-token", "")):
                return self._json(401, {"error": "invalid agent token"})

        normalized = []
        for source in sources:
            item = dict(source)
            item["website_id"] = website_id
            item["agent_id"] = agent_id
            normalized.append(item)
        stored = self.store.replace_agent_log_sources(website_id, agent_id, normalized)
        return self._json(201, {"stored": len(stored), "sources": stored})

    def _upsert_topology_hints(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        website_id = str(payload.get("website_id") or "").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        hints = list(payload.get("hints") or [])
        if not website_id:
            raise ValueError("missing website_id")
        if not agent_id:
            raise ValueError("missing agent_id")
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not self.store.validate_agent_token(agent_id, normalized_headers.get("x-agent-token", "")):
                return self._json(401, {"error": "invalid agent token"})

        observed_at = datetime.now(timezone.utc).isoformat()
        self.store.upsert_website(
            {
                "website_id": website_id,
                "name": payload.get("website_name") or website_id,
                "created_at": observed_at,
            }
        )
        stored = []
        for hint in hints:
            item = dict(hint)
            item["website_id"] = website_id
            item["agent_id"] = agent_id
            item["last_seen_at"] = item.get("last_seen_at") or observed_at
            stored.append(self.store.upsert_topology_hint(item))
        return self._json(201, {"stored": len(stored), "hints": stored})

    def _import_file(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        website_id = str(payload.get("website_id") or "").strip()
        content = str(payload.get("content") or "")
        if not website_id:
            raise ValueError("missing website_id")
        if not content:
            raise ValueError("missing content")

        created_at = datetime.now(timezone.utc).isoformat()
        self.store.upsert_website(
            {
                "website_id": website_id,
                "name": payload.get("website_name") or website_id,
                "created_at": created_at,
            }
        )

        filename = _safe_filename(str(payload.get("filename") or "uploaded.log"))
        import_dir = self.data_dir / "imports" / _safe_path_part(website_id)
        import_dir.mkdir(parents=True, exist_ok=True)
        saved_name = f"{_safe_timestamp(created_at)}-{filename}"
        saved_path = import_dir / saved_name
        saved_path.write_text(content, encoding="utf-8")

        agent_id = str(payload.get("agent_id") or "manual_upload").strip() or "manual_upload"
        agent_role = str(payload.get("agent_role") or "manual").strip() or "manual"
        log_type = str(payload.get("log_type") or "uploaded_file").strip() or "uploaded_file"
        service = str(payload.get("service") or log_type).strip() or log_type

        base_time = datetime.now(timezone.utc)
        imported_lines = 0
        problem_lines = 0
        incident_ids: list[str] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            message = line.strip()
            if not message:
                continue
            imported_lines += 1
            event_time = (base_time + timedelta(microseconds=line_number)).isoformat()
            event = classify_event(
                normalize_event(
                    {
                        "website_id": website_id,
                        "agent_id": agent_id,
                        "agent_role": agent_role,
                        "log_type": log_type,
                        "service": service,
                        "file_path": str(saved_path),
                        "timestamp": event_time,
                        "message": message,
                        "metadata": {
                            "filename": filename,
                            "line_number": line_number,
                            "import_mode": "manual_file",
                        },
                    },
                    observed_at=event_time,
                )
            )
            result = self.store.ingest_event(event)
            if event["severity"] in {"problem", "critical"}:
                problem_lines += 1
            if result["incident_id"]:
                incident_ids.append(result["incident_id"])

        return self._json(
            201,
            {
                "website_id": website_id,
                "filename": filename,
                "saved_path": str(saved_path),
                "imported_lines": imported_lines,
                "problem_lines": problem_lines,
                "incident_ids": sorted(set(incident_ids)),
            },
        )

    def _json(self, status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        return (
            status,
            {"Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
